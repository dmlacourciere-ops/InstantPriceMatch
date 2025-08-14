[CmdletBinding()]
param(
  [string]$ip = "10.0.0.187",
  [int]$port = 4747,
  [string]$country = "CA",
  [string]$store = "Walmart"
)

function Say([string]$msg,[ConsoleColor]$c='Gray') {
  $old=$Host.UI.RawUI.ForegroundColor; $Host.UI.RawUI.ForegroundColor=$c
  Write-Host $msg; $Host.UI.RawUI.ForegroundColor=$old
}

# 1) Activate venv
& "$PSScriptRoot\.venv312\Scripts\Activate.ps1" | Out-Null

# 2) Ensure OPENAI_API_KEY exists (load from openai_key.txt if present, else prompt)
if (-not $env:OPENAI_API_KEY -or $env:OPENAI_API_KEY.Length -lt 20) {
  if (Test-Path "$PSScriptRoot\openai_key.txt") {
    $env:OPENAI_API_KEY = (Get-Content "$PSScriptRoot\openai_key.txt" -Raw).Trim()
    Say "Loaded OPENAI_API_KEY from openai_key.txt (len: $($env:OPENAI_API_KEY.Length))" "Yellow"
  } else {
    Say "OPENAI_API_KEY is missing. Paste it now (not saved):" "Yellow"
    $key = Read-Host "Enter OPENAI API key"
    if ($key) { $env:OPENAI_API_KEY = $key }
  }
}
Say ("OPENAI_API_KEY present: {0}  len: {1}" -f ([bool]$env:OPENAI_API_KEY), $env:OPENAI_API_KEY.Length) "Gray"

# 3) Quick camera probe (optional)
if (Test-Path "$PSScriptRoot\Test-Cam.ps1") {
  . "$PSScriptRoot\Test-Cam.ps1" -ip $ip -port $port
}

# 4) Launch the scanner
$py = "$PSScriptRoot\.venv312\Scripts\python.exe"
$script = "$PSScriptRoot\dev_live_scan_cv.py"
Say "Starting scanner…" "Cyan"
& $py -u $script --ip $ip --port $port --country $country --store $store