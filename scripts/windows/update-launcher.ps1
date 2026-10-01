param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$Branch,

    [Parameter(Mandatory = $true)]
    [int]$ServerPid,

    [Parameter(Mandatory = $true)]
    [string]$UpdaterScript
)

$ErrorActionPreference = "Stop"

function Quote-PowerShellLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

$systemPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $systemPowerShell -PathType Leaf)) {
    $systemPowerShell = "powershell.exe"
}

$logsDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$childOut = Join-Path $logsDir "update-child.stdout.log"
$childErr = Join-Path $logsDir "update-child.stderr.log"
Remove-Item -LiteralPath $childOut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $childErr -Force -ErrorAction SilentlyContinue

$command = "& {0} -ProjectRoot {1} -Repository {2} -Branch {3} -ServerPid {4}" -f @(
    (Quote-PowerShellLiteral $UpdaterScript),
    (Quote-PowerShellLiteral $ProjectRoot),
    (Quote-PowerShellLiteral $Repository),
    (Quote-PowerShellLiteral $Branch),
    [string]$ServerPid
)

$encoded = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($command)
)

$argumentLine = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded"
$process = Start-Process -FilePath $systemPowerShell -ArgumentList $argumentLine -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $childOut -RedirectStandardError $childErr -PassThru
Write-Output $process.Id
exit 0
