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
$RequirementsFile = Join-Path $VenvDir ".dragon_tory_requirements.txt"
$HashFile = Join-Path $VenvDir ".dragon_tory_pyproject.sha256"

$HostAddress = "127.0.0.1"
$Port = 8787
$Url = "http://{0}:{1}/" -f $HostAddress, $Port
$HealthUrl = "http://{0}:{1}/health" -f $HostAddress, $Port

$PythonVersion = "3.12.10"

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

    $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
    if ($signature.Status -ne "Valid") {
        Write-LauncherLog "WARN" "Python installer signature is not valid: $($signature.Status)"
        return $false
    }

    $subject = [string]$signature.SignerCertificate.Subject
    if ($subject -notmatch "Python Software Foundation") {
        Write-LauncherLog "WARN" "Python installer signer is unexpected: $subject"
        return $false
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
    try {
        & $VenvPython -c "import fastapi, uvicorn, pydantic_settings" *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        & $VenvPython -m pip check *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Install-RuntimeDependencies {
    if (-not (Test-Path -LiteralPath $VenvDir)) {
        throw ".venv does not exist."
    }

    & $VenvPython -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-LauncherLog "INFO" "pip is missing. Running ensurepip."
        & $VenvPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            throw "Could not prepare pip."
        }
    }

    $env:DRAGON_PYPROJECT = $PyProject
    $env:DRAGON_REQ = $RequirementsFile

    $extractDependencies = @'
import os
import pathlib
import tomllib

pyproject = pathlib.Path(os.environ["DRAGON_PYPROJECT"])
output = pathlib.Path(os.environ["DRAGON_REQ"])
data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
dependencies = data["project"].get("dependencies", [])
output.write_text("\n".join(dependencies) + "\n", encoding="utf-8")
'@

    & $VenvPython -c $extractDependencies
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read runtime dependencies from pyproject.toml."
    }

    Write-LauncherLog "INFO" "Installing required Python libraries from pyproject.toml."
    & $VenvPython -m pip install --disable-pip-version-check --no-input -r $RequirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "pip could not install one or more required libraries."
    }

    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Python libraries have dependency conflicts."
    }

    if (-not (Test-RuntimeDependencies)) {
        throw "Required runtime libraries failed import validation."
    }
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

    $currentHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PyProject).Hash
    $oldHash = ""
    if (Test-Path -LiteralPath $HashFile -PathType Leaf) {
        $oldHash = (Get-Content -LiteralPath $HashFile -Raw).Trim()
    }

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
    Write-Host ""
    Write-Host "Dragon Tory could not start." -ForegroundColor Red
    Write-Host "Details: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $LauncherLog"
    exit 1
}
