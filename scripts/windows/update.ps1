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

function Write-UpdateLog {
    param([string]$Level, [string]$Message)
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Read-State {
    try {
        if (Test-Path -LiteralPath $StateFile -PathType Leaf) {
            return (Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json)
        }
    } catch {
        Write-UpdateLog "WARN" "Could not read previous update state."
    }
    return [PSCustomObject]@{}
}

function Set-State {
    param(
        [string]$Phase,
        [string]$Message,
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
    $state["error"] = if ($ErrorText) { $ErrorText } else { $null }
    foreach ($key in $Extra.Keys) {
        $state[$key] = $Extra[$key]
    }
    $temp = "$StateFile.tmp"
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $StateFile -Force
}

function Invoke-GitHubJson {
    param([string]$Uri)
    return Invoke-RestMethod -Uri $Uri -Headers @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "Dragon-Tory-Updater"
        "X-GitHub-Api-Version" = "2022-11-28"
    } -TimeoutSec 30
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
        throw "Start.bat is missing after update."
    }

    Start-Process -FilePath "cmd.exe" -ArgumentList @(
        "/d",
        "/c",
        ('call "{0}" --no-browser' -f $StartBat)
    ) -WorkingDirectory $ProjectRoot | Out-Null
}

function Wait-ForHealth {
    param([int]$Seconds = 180)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
            if ($health.status -eq "ok") {
                return $health
            }
        } catch {
            Start-Sleep -Seconds 1
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Dragon Tory did not become healthy after restart."
}

$backupPath = $null
$serverStopped = $false

try {
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    New-Item -ItemType Directory -Path $BackupsDir -Force | Out-Null
    Remove-Item -LiteralPath $ZipFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null

    Set-State "checking" "Проверка последнего коммита GitHub…"
    $repoApi = "https://api.github.com/repos/$Repository"
    $commit = Invoke-GitHubJson "$repoApi/commits/$Branch"
    $remoteSha = [string]$commit.sha

    Set-State "downloading" "Скачивание обновления с GitHub…" "" @{
        remote_sha = $remoteSha
    }
    $zipUrl = "$repoApi/zipball/$Branch"
    Invoke-WebRequest -Uri $zipUrl -OutFile $ZipFile -Headers @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "Dragon-Tory-Updater"
    } -TimeoutSec 120

    if ((Get-Item -LiteralPath $ZipFile).Length -lt 1000) {
        throw "Downloaded GitHub archive is unexpectedly small."
    }

    Expand-Archive -LiteralPath $ZipFile -DestinationPath $ExtractDir -Force
    $sourceRoot = Get-ChildItem -LiteralPath $ExtractDir -Directory | Select-Object -First 1
    if ($null -eq $sourceRoot) {
        throw "Could not find project root inside GitHub archive."
    }
    $sourceRoot = $sourceRoot.FullName
    $ManagedDirs = @(
        Get-ChildItem -LiteralPath $sourceRoot -Force -Directory |
            Where-Object { $ProtectedNames -notcontains $_.Name } |
            ForEach-Object { $_.Name }
    )

    $remoteVersionFile = Join-Path $sourceRoot "src\tooru\version.py"
    if (-not (Test-Path -LiteralPath $remoteVersionFile -PathType Leaf)) {
        throw "Downloaded archive does not contain src\tooru\version.py."
    }
    $remoteText = Get-Content -LiteralPath $remoteVersionFile -Raw -Encoding UTF8
    $versionMatch = [regex]::Match(
        $remoteText,
        '(?m)^__version__\s*=\s*"([^"]+)"'
    )
    if (-not $versionMatch.Success) {
        throw "Could not read version from src\tooru\version.py."
    }
    $remoteVersion = $versionMatch.Groups[1].Value

    Set-State "backing_up" "Создание резервной копии текущего кода…"
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = Join-Path $BackupsDir "update-$stamp"
    Copy-ProjectSnapshot $backupPath

    Set-State "stopping" "Остановка Dragon Tory перед установкой…"
    try {
        $serverProcess = Get-Process -Id $ServerPid -ErrorAction Stop
        Stop-Process -Id $serverProcess.Id -Force
        $serverProcess.WaitForExit()
        $serverStopped = $true
    } catch {
        Write-UpdateLog "WARN" "Server process was already stopped."
        $serverStopped = $true
    }
    Start-Sleep -Seconds 1

    Set-State "installing" "Установка файлов новой версии…" "" @{
        backup_path = $backupPath
    }
    Install-Archive $sourceRoot

    Set-State "restarting" "Перезапуск Dragon Tory и установка зависимостей…" "" @{
        backup_path = $backupPath
    }
    Start-DragonTory

    Set-State "verifying" "Проверка новой версии после перезапуска…" "" @{
        backup_path = $backupPath
    }
    $health = Wait-ForHealth 180

    Set-State "success" "Обновление установлено успешно." "" @{
        installed_sha = $remoteSha
        remote_sha = $remoteSha
        installed_version = [string]$health.version
        local_version = [string]$health.version
        remote_version = [string]$health.version
        update_available = $false
        last_updated_at = (Get-Date).ToUniversalTime().ToString("o")
        backup_path = $backupPath
    }
    Write-UpdateLog "OK" "Update completed: $remoteSha / $remoteVersion"
    exit 0
} catch {
    $errorText = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
    Write-UpdateLog "ERROR" $errorText

    if ($serverStopped -and $backupPath -and (Test-Path -LiteralPath $backupPath)) {
        try {
            Set-State "rolling_back" "Ошибка обновления. Выполняется автоматический откат…" $errorText @{
                backup_path = $backupPath
            }
            Restore-Backup $backupPath
            Start-DragonTory
            Wait-ForHealth 180 | Out-Null
            Set-State "failed" "Обновление не установлено. Предыдущая версия восстановлена." $errorText @{
                backup_path = $backupPath
                rolled_back = $true
            }
            Write-UpdateLog "WARN" "Rollback completed successfully."
        } catch {
            $rollbackError = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
            Set-State "failed" "Ошибка обновления и автоматического отката." "$errorText | Rollback: $rollbackError" @{
                backup_path = $backupPath
                rolled_back = $false
            }
            Write-UpdateLog "ERROR" "Rollback failed: $rollbackError"
        }
    } else {
        Set-State "failed" "Обновление не установлено." $errorText
    }
    exit 1
}
