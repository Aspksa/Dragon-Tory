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
$process = Start-Process -FilePath $systemPowerShell -ArgumentList $argumentLine -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
Write-Output $process.Id
exit 0
