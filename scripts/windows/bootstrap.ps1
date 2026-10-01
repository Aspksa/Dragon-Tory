param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [switch]$NoBrowser,

    [switch]$Check
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
} catch {
    # Console encoding is cosmetic; startup must still work.
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$PyProject = Join-Path $ProjectRoot "pyproject.toml"
$MainFile = Join-Path $ProjectRoot "src\tooru\main.py"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RuntimeDir = Join-Path $ProjectRoot "runtime"
$PythonHome = Join-Path $RuntimeDir "python"
$LocalPython = Join-Path $PythonHome "python.exe"
$DownloadsDir = Join-Path $RuntimeDir "downloads"
$LogsDir = Join-Path $ProjectRoot "logs"
$LauncherLog = Join-Path $LogsDir "launcher.log"
$HashFile = Join-Path $VenvDir ".dragon_tory_pyproject.sha256"

$HostAddress = "127.0.0.1"
$Port = 8787
$Url = "http://{0}:{1}/" -f $HostAddress, $Port
$HealthUrl = "http://{0}:{1}/health" -f $HostAddress, $Port

$PythonVersion = "3.12.10"

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

function Write-LauncherLog {
    param(
        [string]$Level,
        [string]$Message
    )

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] [$Level] $Message"
    Write-Host $line

    try {
        if (-not (Test-Path -LiteralPath $LogsDir)) {
            New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
        }
        Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
    } catch {
        # Logging must never block startup.
    }
}

function Assert-ProjectLayout {
    if (-not (Test-Path -LiteralPath $PyProject -PathType Leaf)) {
        throw "pyproject.toml was not found next to Start.bat."
    }
    if (-not (Test-Path -LiteralPath $MainFile -PathType Leaf)) {
        throw "src\tooru\main.py was not found. The project copy is incomplete."
    }
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        throw "Windows PowerShell 5.1 or newer is required."
    }
}

function Test-DragonHealth {
    try {
        $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1
        return ($health.status -eq "ok")
    } catch {
        return $false
    }
}

function New-PythonCandidate {
    param(
        [string]$Executable,
        [string[]]$PrefixArguments,
        [string]$Label
    )

    return [PSCustomObject]@{
        Executable = $Executable
        PrefixArguments = @($PrefixArguments)
        Label = $Label
    }
}

function Test-PythonCandidate {
    param($Candidate)

    if ($null -eq $Candidate) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $Candidate.Executable -PathType Leaf)) {
        return $false
    }

    $arguments = @()
    $arguments += $Candidate.PrefixArguments
    $arguments += "-c"
    $arguments += "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"

    try {
        & $Candidate.Executable @arguments *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    if (Test-Path -LiteralPath $LocalPython -PathType Leaf) {
        $local = New-PythonCandidate -Executable $LocalPython -PrefixArguments @() -Label "local runtime"
        if (Test-PythonCandidate $local) {
            return $local
        }

        Write-LauncherLog "WARN" "Local Python runtime is invalid and will be rebuilt."
        Remove-Item -LiteralPath $PythonHome -Recurse -Force -ErrorAction SilentlyContinue
    }

    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        foreach ($version in @("-3.12", "-3.11")) {
            $candidate = New-PythonCandidate -Executable $py.Source -PrefixArguments @($version) -Label "Python Launcher $version"
            if (Test-PythonCandidate $candidate) {
                return $candidate
            }
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $candidate = New-PythonCandidate -Executable $python.Source -PrefixArguments @() -Label "python.exe from PATH"
        if (Test-PythonCandidate $candidate) {
            return $candidate
        }
    }

    return $null
}

function Get-PythonInstallerArchitecture {
    $nativeArch = $env:PROCESSOR_ARCHITEW6432
    if ([string]::IsNullOrWhiteSpace($nativeArch)) {
        $nativeArch = $env:PROCESSOR_ARCHITECTURE
    }

    if ($nativeArch -match "ARM64") {
        return "arm64"
    }
    if ($nativeArch -match "AMD64") {
        return "amd64"
    }

    throw "Dragon Tory automatic Python setup currently requires 64-bit Windows (x64 or ARM64). Detected: $nativeArch"
}

function Test-PythonInstaller {
    param([string]$InstallerPath)

    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        return $false
    }

    $file = Get-Item -LiteralPath $InstallerPath
    if ($file.Length -lt 20000000) {
        Write-LauncherLog "WARN" "Cached Python installer is too small and will be downloaded again."
        return $false
    }

    $expectedHashes = @{
        "python-3.12.10-amd64.exe" = "67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB"
        "python-3.12.10-arm64.exe" = "377AC8FD478987940088E879441E702A71B53164D2A1E6F1D51FF77A7E470258"
    }

    $name = $file.Name.ToLowerInvariant()
    if (-not $expectedHashes.ContainsKey($name)) {
        Write-LauncherLog "WARN" "No pinned SHA-256 is configured for $($file.Name)."
        return $false
    }

    $actualHash = (Get-Sha256Hex -Path $InstallerPath).ToUpperInvariant()
    if ($actualHash -ne $expectedHashes[$name]) {
        Write-LauncherLog "WARN" "Python installer SHA-256 mismatch."
        return $false
    }

    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath -ErrorAction Stop
        if ($signature.Status -ne "Valid") {
            Write-LauncherLog "WARN" "Python installer signature is not valid: $($signature.Status)"
            return $false
        }

        $subject = [string]$signature.SignerCertificate.Subject
        if ($subject -notmatch "Python Software Foundation") {
            Write-LauncherLog "WARN" "Python installer signer is unexpected: $subject"
            return $false
        }

        Write-LauncherLog "OK" "Python installer SHA-256 and Authenticode signature are valid."
    } catch {
        Write-LauncherLog "WARN" "Authenticode API is unavailable; pinned SHA-256 verification succeeded."
    }

    return $true
}

function Install-LocalPython {
    $arch = Get-PythonInstallerArchitecture
    $installerName = "python-$PythonVersion-$arch.exe"
    $installerPath = Join-Path $DownloadsDir $installerName
    $pythonUrl = "https://www.python.org/ftp/python/$PythonVersion/$installerName"

    New-Item -ItemType Directory -Path $DownloadsDir -Force | Out-Null

    if (-not (Test-PythonInstaller $installerPath)) {
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
        Write-LauncherLog "INFO" "Python was not found. Downloading official Python $PythonVersion ($arch)."
        Write-LauncherLog "INFO" "Source: $pythonUrl"

        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath -UseBasicParsing
        } catch {
            $curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue
            if ($null -eq $curl) {
                throw "Python download failed and curl.exe is unavailable. $($_.Exception.Message)"
            }

            & $curl.Source "-fL" "--retry" "3" "--connect-timeout" "15" "-o" $installerPath $pythonUrl
            if ($LASTEXITCODE -ne 0) {
                throw "Python download failed through both PowerShell and curl.exe."
            }
        }

        if (-not (Test-PythonInstaller $installerPath)) {
            throw "Downloaded Python installer failed size or Authenticode signature verification."
        }
    } else {
        Write-LauncherLog "INFO" "Using verified cached Python installer."
    }

    if (Test-Path -LiteralPath $PythonHome) {
        Remove-Item -LiteralPath $PythonHome -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $PythonHome -Force | Out-Null

    Write-LauncherLog "INFO" "Installing Python locally into: $PythonHome"

    $installArguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "Include_launcher=0",
        "Include_pip=1",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0",
        "AssociateFiles=0",
        "PrependPath=0",
        ('TargetDir="{0}"' -f $PythonHome)
    )

    $process = Start-Process -FilePath $installerPath -ArgumentList $installArguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Python installer exited with code $($process.ExitCode)."
    }

    $candidate = New-PythonCandidate -Executable $LocalPython -PrefixArguments @() -Label "downloaded local Python $PythonVersion"
    if (-not (Test-PythonCandidate $candidate)) {
        throw "Python installation completed but runtime validation failed."
    }

    Write-LauncherLog "OK" "Local Python $PythonVersion is ready."
    return $candidate
}

function New-ProjectVenv {
    param($Candidate)

    if (Test-Path -LiteralPath $VenvDir) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-LauncherLog "INFO" "Creating project virtual environment with $($Candidate.Label)."

    $arguments = @()
    $arguments += $Candidate.PrefixArguments
    $arguments += "-m"
    $arguments += "venv"
    $arguments += $VenvDir

    & $Candidate.Executable @arguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "Could not create .venv."
    }
}

function Test-Venv {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        return $false
    }

    try {
        & $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-RuntimeDependencies {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $probe = "import importlib.util as u; mods=('fastapi','uvicorn','pydantic_settings'); raise SystemExit(0 if all(u.find_spec(m) for m in mods) else 1)"
        & $VenvPython -c $probe 1>$null 2>$null
        $probeExit = $LASTEXITCODE
        if ($probeExit -ne 0) {
            return $false
        }

        & $VenvPython -m pip check 1>$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Install-RuntimeDependencies {
    if (-not (Test-Path -LiteralPath $VenvDir)) {
        throw ".venv does not exist."
    }

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $pipVersionOutput = & $VenvPython -m pip --version 2>&1
        $pipVersionExit = $LASTEXITCODE

        if ($pipVersionExit -ne 0) {
            Write-LauncherLog "INFO" "pip is missing or unhealthy. Running ensurepip."
            $ensureOutput = & $VenvPython -m ensurepip --upgrade 2>&1
            $ensureExit = $LASTEXITCODE
            foreach ($line in $ensureOutput) {
                Write-Host $line
                Add-Content -LiteralPath $LauncherLog -Value ([string]$line) -Encoding UTF8
            }
            if ($ensureExit -ne 0) {
                throw "Could not prepare pip. ensurepip exit code: $ensureExit"
            }
        } else {
            Write-LauncherLog "OK" ("pip is available: " + (($pipVersionOutput | Out-String).Trim()))
        }

        Write-LauncherLog "INFO" "Installing Dragon Tory and required libraries from pyproject.toml."
        $installOutput = & $VenvPython -m pip install --disable-pip-version-check --no-input --editable $ProjectRoot 2>&1
        $installExit = $LASTEXITCODE
        foreach ($line in $installOutput) {
            Write-Host $line
            Add-Content -LiteralPath $LauncherLog -Value ([string]$line) -Encoding UTF8
        }
        if ($installExit -ne 0) {
            throw "pip could not install Dragon Tory or one or more required libraries. Exit code: $installExit"
        }

        Write-LauncherLog "INFO" "Checking installed Python dependency consistency."
        $checkOutput = & $VenvPython -m pip check 2>&1
        $checkExit = $LASTEXITCODE
        foreach ($line in $checkOutput) {
            Write-Host $line
            Add-Content -LiteralPath $LauncherLog -Value ([string]$line) -Encoding UTF8
        }
        if ($checkExit -ne 0) {
            throw "Installed Python libraries have dependency conflicts. pip check exit code: $checkExit"
        }
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    if (-not (Test-RuntimeDependencies)) {
        throw "Required runtime libraries failed import validation."
    }

    Write-LauncherLog "OK" "Python libraries passed pip check and import validation."
}

try {
    Assert-ProjectLayout

    if (-not (Test-Path -LiteralPath $LogsDir)) {
        New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    }

    Write-LauncherLog "INFO" "Dragon Tory project root: $ProjectRoot"

    if ($ProjectRoot.Length -gt 180) {
        Write-LauncherLog "WARN" "The project path is very long. Windows/Python tools may hit legacy path limits."
    }

    if ($Check) {
        Write-LauncherLog "OK" "Portable launcher structure is valid."
        Write-LauncherLog "OK" "Unicode/spaces are supported by the PowerShell bootstrap."
        exit 0
    }

    Set-Location -LiteralPath $ProjectRoot
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:TOORU_DATA_DIR = Join-Path $ProjectRoot "data"

    if (Test-DragonHealth) {
        Write-LauncherLog "OK" "Dragon Tory is already running."
        if (-not $NoBrowser) {
            Start-Process $Url
        }
        exit 0
    }

    $forceLocalPython = ($env:TOORU_FORCE_LOCAL_PYTHON -eq "1")

    if ($forceLocalPython -and (Test-Path -LiteralPath $VenvDir)) {
        Write-LauncherLog "INFO" "Forced local-Python validation: rebuilding .venv."
        Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Venv)) {
        if (Test-Path -LiteralPath $VenvDir) {
            Write-LauncherLog "WARN" "Existing .venv is invalid (often caused by moving the drive). Rebuilding it."
            Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        }

        if ($forceLocalPython) {
            Write-LauncherLog "INFO" "Forcing project-local Python bootstrap."
            $candidate = Install-LocalPython
        } else {
            $candidate = Find-Python
            if ($null -eq $candidate) {
                $candidate = Install-LocalPython
            }
        }

        New-ProjectVenv $candidate
    }

    Write-LauncherLog "OK" "Virtual environment: $VenvPython"
    Write-LauncherLog "INFO" "Computing pyproject integrity hash."

    $currentHash = Get-Sha256Hex -Path $PyProject
    $oldHash = ""
    if (Test-Path -LiteralPath $HashFile -PathType Leaf) {
        $oldHash = (Get-Content -LiteralPath $HashFile -Raw).Trim()
    }

    Write-LauncherLog "INFO" "Checking runtime dependency state."
    $dependenciesReady = Test-RuntimeDependencies
    if ((-not $dependenciesReady) -or ($currentHash -ne $oldHash)) {
        Install-RuntimeDependencies
        Set-Content -LiteralPath $HashFile -Value $currentHash -Encoding ASCII
    } else {
        Write-LauncherLog "OK" "Required Python libraries are already installed and consistent."
    }

    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot "data") -Force | Out-Null

    Write-LauncherLog "INFO" "Starting Dragon Tory on $Url"
    $serverProcess = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "tooru.main") -WorkingDirectory $ProjectRoot -PassThru

    $ready = $false
    for ($i = 0; $i -lt 80; $i++) {
        if (Test-DragonHealth) {
            $ready = $true
            break
        }

        if ($serverProcess.HasExited) {
            break
        }

        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        $exitDescription = "still running"
        if ($serverProcess.HasExited) {
            $exitDescription = "exit code $($serverProcess.ExitCode)"
        }
        throw "Dragon Tory backend did not become ready ($exitDescription). See $LauncherLog."
    }

    Write-LauncherLog "OK" "Dragon Tory is ready."

    if (-not $NoBrowser) {
        Write-LauncherLog "INFO" "Opening default browser: $Url"
        Start-Process $Url
    }

    Write-LauncherLog "OK" "Startup complete."
    exit 0
} catch {
    Write-LauncherLog "ERROR" $_.Exception.Message
    if ($_.ScriptStackTrace) {
        Write-LauncherLog "ERROR" ("PowerShell stack: " + $_.ScriptStackTrace)
    }
    try {
        Add-Content -LiteralPath $LauncherLog -Value ($_ | Out-String) -Encoding UTF8
    } catch {
        # Do not mask the original startup failure.
    }
    Write-Host ""
    Write-Host "Dragon Tory could not start." -ForegroundColor Red
    Write-Host "Details: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $LauncherLog"
    exit 1
}
