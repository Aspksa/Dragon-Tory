param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$Branch,

    [Parameter(Mandatory = $true)]
    [int]$ServerPid
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$StateDir = Join-Path $ProjectRoot "data\update"
$StateFile = Join-Path $StateDir "state.json"
$HistoryFile = Join-Path $StateDir "history.json"
$LogsDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogsDir "update.log"
$WorkDir = Join-Path $ProjectRoot "runtime\update"
$ZipFile = Join-Path $WorkDir "update.zip"
$ExtractDir = Join-Path $WorkDir "extracted"
$BackupsDir = Join-Path $ProjectRoot "backups"
$HealthUrl = "http://127.0.0.1:8787/health"
$StartBat = Join-Path $ProjectRoot "Start.bat"

$ProtectedNames = @(
    ".env",
    ".venv",
    "data",
    "runtime",
    "logs",
    "backups",
    ".git"
)
$ManagedDirs = @()
$DownloadedFiles = @()
$ChangedFiles = @()
$NewFiles = @()
$RemovedFiles = @()
$backupPath = $null
$serverStopped = $false
$initialState = $null
$fromVersion = ""
$updateStartedAt = ""

function Write-UpdateLog {
    param([string]$Level, [string]$Message)
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    $line = "[{0}] [{1}] {2}" -f (
        Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    ), $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Read-State {
    try {
        if (Test-Path -LiteralPath $StateFile -PathType Leaf) {
            return (
                Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 |
                    ConvertFrom-Json
            )
        }
    } catch {
        Write-UpdateLog "WARN" "Не удалось прочитать предыдущее состояние обновления."
    }
    return [PSCustomObject]@{}
}

function Set-State {
    param(
        [string]$Phase,
        [string]$Message,
        [int]$Progress = -1,
        [string]$ErrorText = "",
        [hashtable]$Extra = @{}
    )

    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    $old = Read-State
    $state = @{}
    if ($null -ne $old) {
        foreach ($property in $old.PSObject.Properties) {
            $state[$property.Name] = $property.Value
        }
    }

    $state["phase"] = $Phase
    $state["message"] = $Message
    $state["heartbeat_at"] = (Get-Date).ToUniversalTime().ToString("o")
    if ($Progress -ge 0) {
        $state["progress_percent"] = $Progress
    }
    $state["error"] = if ($ErrorText) { $ErrorText } else { $null }

    foreach ($key in $Extra.Keys) {
        $state[$key] = $Extra[$key]
    }

    $temp = "$StateFile.tmp"
    $state |
        ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $StateFile -Force
}

function Add-History {
    param(
        [string]$Result,
        [string]$Description,
        [string]$ToVersion,
        [string]$Sha,
        [string]$ErrorText = "",
        [bool]$RolledBack = $false
    )

    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    $items = @()

    try {
        if (Test-Path -LiteralPath $HistoryFile -PathType Leaf) {
            $raw = (
                Get-Content -LiteralPath $HistoryFile -Raw -Encoding UTF8 |
                    ConvertFrom-Json
            )
            if ($null -ne $raw) {
                $items = @($raw)
            }
        }
    } catch {
        Write-UpdateLog "WARN" "Не удалось прочитать историю обновлений."
        $items = @()
    }

    $entry = [ordered]@{
        started_at = $updateStartedAt
        finished_at = (Get-Date).ToUniversalTime().ToString("o")
        from_version = $fromVersion
        to_version = $ToVersion
        sha = $Sha
        result = $Result
        description = $Description
        error = if ($ErrorText) { $ErrorText } else { $null }
        rolled_back = $RolledBack
        backup_path = $backupPath
        downloaded_files = @($DownloadedFiles)
        changed_files = @($ChangedFiles)
        new_files = @($NewFiles)
        removed_files = @($RemovedFiles)
    }

    $items += [PSCustomObject]$entry
    if ($items.Count -gt 100) {
        $items = @($items | Select-Object -Last 100)
    }

    $temp = "$HistoryFile.tmp"
    $items |
        ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $HistoryFile -Force
}

function Invoke-GitHubJson {
    param([string]$Uri)
    return Invoke-RestMethod -Uri $Uri -Headers @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "Dragon-Tory-Updater"
        "X-GitHub-Api-Version" = "2022-11-28"
    } -TimeoutSec 30
}

function Get-Sha256Hex {
    param([string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace("-", "")
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function Convert-DisplayVersion {
    param([string]$Value)

    $matches = [regex]::Matches($Value, "\d+")
    $parts = @(0, 0, 0)
    for ($i = 0; $i -lt [Math]::Min(3, $matches.Count); $i++) {
        $parts[$i] = [int]$matches[$i].Value
    }
    return "{0:D2}.{1:D2}.{2:D2}" -f $parts[0], $parts[1], $parts[2]
}

function Get-RelativePathText {
    param([string]$Root, [string]$FullName)
    $relative = $FullName.Substring($Root.Length)
    if ($relative.StartsWith("\") -or $relative.StartsWith("/")) {
        $relative = $relative.Substring(1)
    }
    return $relative.Replace("\", "/")
}

function Build-FileManifest {
    param([string]$SourceRoot)

    $remoteFiles = @(
        Get-ChildItem -LiteralPath $SourceRoot -Force -File -Recurse |
            ForEach-Object {
                Get-RelativePathText $SourceRoot $_.FullName
            } |
            Sort-Object
    )

    $script:DownloadedFiles = @($remoteFiles)
    $remoteSet = @{}
    foreach ($relative in $remoteFiles) {
        $remoteSet[$relative.ToLowerInvariant()] = $true
        $source = Join-Path $SourceRoot ($relative.Replace("/", "\"))
        $target = Join-Path $ProjectRoot ($relative.Replace("/", "\"))

        $top = $relative.Split("/")[0]
        if ($ProtectedNames -contains $top) {
            continue
        }

        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            $script:NewFiles += $relative
            continue
        }

        if ((Get-Sha256Hex $source) -ne (Get-Sha256Hex $target)) {
            $script:ChangedFiles += $relative
        }
    }

    foreach ($dir in $ManagedDirs) {
        $currentDir = Join-Path $ProjectRoot $dir
        if (-not (Test-Path -LiteralPath $currentDir -PathType Container)) {
            continue
        }

        Get-ChildItem -LiteralPath $currentDir -Force -File -Recurse |
            ForEach-Object {
                $relative = Get-RelativePathText $ProjectRoot $_.FullName
                if (-not $remoteSet.ContainsKey($relative.ToLowerInvariant())) {
                    $script:RemovedFiles += $relative
                }
            }
    }

    $script:DownloadedFiles = @($script:DownloadedFiles | Sort-Object -Unique)
    $script:ChangedFiles = @($script:ChangedFiles | Sort-Object -Unique)
    $script:NewFiles = @($script:NewFiles | Sort-Object -Unique)
    $script:RemovedFiles = @($script:RemovedFiles | Sort-Object -Unique)
}

function Copy-ProjectSnapshot {
    param([string]$Destination)

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null

    foreach ($dir in $ManagedDirs) {
        $source = Join-Path $ProjectRoot $dir
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $Destination -Recurse -Force
        }
    }

    Get-ChildItem -LiteralPath $ProjectRoot -Force -File | ForEach-Object {
        if ($ProtectedNames -notcontains $_.Name) {
            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Force
        }
    }
}

function Install-Archive {
    param([string]$SourceRoot)

    foreach ($dir in $ManagedDirs) {
        $sourceDir = Join-Path $SourceRoot $dir
        $targetDir = Join-Path $ProjectRoot $dir
        if (Test-Path -LiteralPath $sourceDir) {
            if (Test-Path -LiteralPath $targetDir) {
                Remove-Item -LiteralPath $targetDir -Recurse -Force
            }
            Copy-Item -LiteralPath $sourceDir -Destination $ProjectRoot -Recurse -Force
        }
    }

    Get-ChildItem -LiteralPath $SourceRoot -Force -File | ForEach-Object {
        if ($ProtectedNames -notcontains $_.Name) {
            Copy-Item -LiteralPath $_.FullName -Destination $ProjectRoot -Force
        }
    }
}

function Restore-Backup {
    param([string]$BackupRoot)

    foreach ($dir in $ManagedDirs) {
        $targetDir = Join-Path $ProjectRoot $dir
        if (Test-Path -LiteralPath $targetDir) {
            Remove-Item -LiteralPath $targetDir -Recurse -Force -ErrorAction SilentlyContinue
        }

        $backupDir = Join-Path $BackupRoot $dir
        if (Test-Path -LiteralPath $backupDir) {
            Copy-Item -LiteralPath $backupDir -Destination $ProjectRoot -Recurse -Force
        }
    }

    Get-ChildItem -LiteralPath $BackupRoot -Force -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $ProjectRoot -Force
    }
}

function Start-DragonTory {
    if (-not (Test-Path -LiteralPath $StartBat -PathType Leaf)) {
        throw "Start.bat отсутствует после установки обновления."
    }

    Start-Process -FilePath "cmd.exe" -ArgumentList @(
        "/d",
        "/c",
        ('call "{0}" --no-browser' -f $StartBat)
    ) -WorkingDirectory $ProjectRoot | Out-Null
}

function Wait-ForHealth {
    param([int]$Seconds = 240)

    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
            if ($health.status -eq "ok") {
                return $health
            }
        } catch {
            Start-Sleep -Milliseconds 800
        }
        Start-Sleep -Milliseconds 500
    }

    throw "Dragon Tory не стал доступен после автоматического перезапуска."
}

try {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    New-Item -ItemType Directory -Path $BackupsDir -Force | Out-Null

    $initialState = Read-State
    $fromVersion = [string]$initialState.local_version
    $updateStartedAt = [string]$initialState.update_started_at
    if ([string]::IsNullOrWhiteSpace($updateStartedAt)) {
        $updateStartedAt = (Get-Date).ToUniversalTime().ToString("o")
    }

    Remove-Item -LiteralPath $ZipFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null

    Set-State -Phase "checking" -Message "Проверка последнего коммита GitHub…" -Progress 5
    Write-UpdateLog "INFO" "Проверяется последний коммит GitHub."

    $repoApi = "https://api.github.com/repos/$Repository"
    $commit = Invoke-GitHubJson "$repoApi/commits/$Branch"
    $remoteSha = [string]$commit.sha

    Set-State -Phase "downloading" -Message "Скачивание архива проекта с GitHub…" -Progress 15 -Extra @{
        remote_sha = $remoteSha
    }
    Write-UpdateLog "INFO" "Скачивается архив GitHub: $remoteSha"

    $zipUrl = "$repoApi/zipball/$Branch"
    Invoke-WebRequest -Uri $zipUrl -OutFile $ZipFile -Headers @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "Dragon-Tory-Updater"
    } -TimeoutSec 120

    if ((Get-Item -LiteralPath $ZipFile).Length -lt 1000) {
        throw "Скачанный архив GitHub имеет недопустимо маленький размер."
    }

    Set-State -Phase "extracting" -Message "Распаковка архива и сверка файлов…" -Progress 30
    Write-UpdateLog "INFO" "Архив скачан. Выполняется распаковка и сверка файлов."

    Expand-Archive -LiteralPath $ZipFile -DestinationPath $ExtractDir -Force
    $sourceRoot = (
        Get-ChildItem -LiteralPath $ExtractDir -Directory |
            Select-Object -First 1
    )
    if ($null -eq $sourceRoot) {
        throw "В архиве GitHub не найдена корневая папка проекта."
    }
    $sourceRoot = $sourceRoot.FullName

    $ManagedDirs = @(
        Get-ChildItem -LiteralPath $sourceRoot -Force -Directory |
            Where-Object { $ProtectedNames -notcontains $_.Name } |
            ForEach-Object { $_.Name }
    )

    $remoteVersionFile = Join-Path $sourceRoot "src\tooru\version.py"
    if (-not (Test-Path -LiteralPath $remoteVersionFile -PathType Leaf)) {
        throw "В архиве отсутствует src\tooru\version.py."
    }

    $remoteText = Get-Content -LiteralPath $remoteVersionFile -Raw -Encoding UTF8
    $versionMatch = [regex]::Match(
        $remoteText,
        '(?m)^__version__\s*=\s*"([^"]+)"'
    )
    if (-not $versionMatch.Success) {
        throw "Не удалось определить версию скачанного проекта."
    }
    $remoteVersion = Convert-DisplayVersion $versionMatch.Groups[1].Value

    Build-FileManifest $sourceRoot

    $manifestMessage = "Сверка завершена: файлов {0}, изменено {1}, новых {2}, удалено {3}." -f $DownloadedFiles.Count, $ChangedFiles.Count, $NewFiles.Count, $RemovedFiles.Count
    Set-State -Phase "extracting" -Message $manifestMessage -Progress 40 -Extra @{
        remote_version = $remoteVersion
        downloaded_files = @($DownloadedFiles)
        changed_files = @($ChangedFiles)
        new_files = @($NewFiles)
        removed_files = @($RemovedFiles)
    }

    Set-State -Phase "backing_up" -Message "Создание резервной копии текущего кода…" -Progress 50
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = Join-Path $BackupsDir "update-$stamp"
    Copy-ProjectSnapshot $backupPath
    Write-UpdateLog "INFO" "Резервная копия создана: $backupPath"

    Set-State -Phase "stopping" -Message "Остановка Dragon Tory перед установкой…" -Progress 60 -Extra @{
        backup_path = $backupPath
    }

    try {
        $serverProcess = Get-Process -Id $ServerPid -ErrorAction Stop
        Stop-Process -Id $serverProcess.Id -Force
        $serverProcess.WaitForExit()
        $serverStopped = $true
    } catch {
        Write-UpdateLog "WARN" "Сервер уже был остановлен."
        $serverStopped = $true
    }

    Start-Sleep -Seconds 1

    Set-State -Phase "installing" -Message "Установка файлов новой версии…" -Progress 70 -Extra @{
        backup_path = $backupPath
    }
    Install-Archive $sourceRoot
    Write-UpdateLog "INFO" "Файлы новой версии установлены."

    Set-State -Phase "restarting" -Message "Перезапуск Dragon Tory и проверка новых зависимостей…" -Progress 85 -Extra @{
        backup_path = $backupPath
    }
    Start-DragonTory

    Set-State -Phase "verifying" -Message "Проверка новой версии после перезапуска…" -Progress 92 -Extra @{
        backup_path = $backupPath
    }
    $health = Wait-ForHealth 240

    $installedVersion = [string]$health.version
    $description = "Обновление с {0} до {1} успешно установлено." -f $fromVersion, $installedVersion

    Set-State -Phase "success" -Message $description -Progress 100 -Extra @{
        installed_sha = $remoteSha
        remote_sha = $remoteSha
        installed_version = $installedVersion
        local_version = $installedVersion
        remote_version = $installedVersion
        update_available = $false
        last_updated_at = (Get-Date).ToUniversalTime().ToString("o")
        backup_path = $backupPath
        downloaded_files = @($DownloadedFiles)
        changed_files = @($ChangedFiles)
        new_files = @($NewFiles)
        removed_files = @($RemovedFiles)
    }

    Add-History -Result "success" -Description $description -ToVersion $installedVersion -Sha $remoteSha
    Write-UpdateLog "OK" $description
    exit 0
} catch {
    $errorText = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
    Write-UpdateLog "ERROR" $errorText

    $targetVersion = ""
    try {
        $currentState = Read-State
        $targetVersion = [string]$currentState.remote_version
    } catch {}

    if ($serverStopped -and $backupPath -and (Test-Path -LiteralPath $backupPath)) {
        try {
            Set-State -Phase "rolling_back" -Message "Ошибка обновления. Выполняется автоматический откат…" -Progress 95 -ErrorText $errorText -Extra @{
                backup_path = $backupPath
            }

            Restore-Backup $backupPath
            Start-DragonTory
            Wait-ForHealth 240 | Out-Null

            $description = "Обновление с {0} до {1} не установлено. Предыдущая версия восстановлена автоматически." -f $fromVersion, $targetVersion

            Set-State -Phase "failed" -Message $description -Progress 0 -ErrorText $errorText -Extra @{
                backup_path = $backupPath
                rolled_back = $true
                downloaded_files = @($DownloadedFiles)
                changed_files = @($ChangedFiles)
                new_files = @($NewFiles)
                removed_files = @($RemovedFiles)
            }
            Add-History -Result "failed" -Description $description -ToVersion $targetVersion -Sha $remoteSha -ErrorText $errorText -RolledBack $true
            Write-UpdateLog "WARN" "Автоматический откат выполнен успешно."
        } catch {
            $rollbackError = (
                "$($_.Exception.GetType().Name): $($_.Exception.Message)"
            )
            $description = (
                "Ошибка обновления и автоматического отката."
            )
            $combinedError = "$errorText | Ошибка отката: $rollbackError"
            Set-State -Phase "failed" -Message $description -Progress 0 -ErrorText $combinedError -Extra @{
                backup_path = $backupPath
                rolled_back = $false
                downloaded_files = @($DownloadedFiles)
                changed_files = @($ChangedFiles)
                new_files = @($NewFiles)
                removed_files = @($RemovedFiles)
            }
            Add-History -Result "failed" -Description $description -ToVersion $targetVersion -Sha $remoteSha -ErrorText $combinedError -RolledBack $false
            Write-UpdateLog "ERROR" "Ошибка отката: $rollbackError"
        }
    } else {
        $description = "Обновление не установлено: $errorText"
        Set-State -Phase "failed" -Message $description -Progress 0 -ErrorText $errorText -Extra @{
            downloaded_files = @($DownloadedFiles)
            changed_files = @($ChangedFiles)
            new_files = @($NewFiles)
            removed_files = @($RemovedFiles)
        }
        Add-History -Result "failed" -Description $description -ToVersion $targetVersion -Sha $remoteSha -ErrorText $errorText -RolledBack $false
    }

    exit 1
}
