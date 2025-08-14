# overnight.ps1
# Runs download -> embed using the venv python, writes logs to .\logs,
# and always starts from the script folder (so paths are correct).

[CmdletBinding()]
param(
    [int]$Limit = 0,
    [int]$Workers = 8
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

# Always run from where this script lives
Set-Location -Path $PSScriptRoot

# Ensure logs dir
$logsDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

# Timestamped log names
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dlLog = Join-Path $logsDir "download_$stamp.log"
$emLog = Join-Path $logsDir "embed_$stamp.log"

# Paths
$py   = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$main = Join-Path $PSScriptRoot "instant_price_match.py"

if (-not (Test-Path $py))   { Write-Error "Python not found: $py"; exit 1 }
if (-not (Test-Path $main)) { Write-Error "Script not found: $main"; exit 1 }

Write-Host "=== DOWNLOADING images (all) ==="
& $py -u $main --mode download --limit $Limit --workers $Workers 2>&1 | Tee-Object -FilePath $dlLog

Write-Host "=== EMBEDDING images ==="
& $py -u $main --mode embed --limit $Limit 2>&1 | Tee-Object -FilePath $emLog

Write-Host ""
Write-Host "Done."
Write-Host "Logs:"
Write-Host "  $dlLog"
Write-Host "  $emLog"
