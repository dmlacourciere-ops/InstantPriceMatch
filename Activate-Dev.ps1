# Activate-Dev.ps1
# Loads variables from .env (not committed) and activates the venv

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvActivate = Join-Path $projectRoot ".venv\Scripts\Activate.ps1"

$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    $pair = $_ -split '=', 2
    if ($pair.Length -eq 2) {
      $name = $pair[0].Trim()
      $value = $pair[1].Trim()
      [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
} else {
  Write-Host "No .env file found. Create C:\Projects\InstantPriceMatch\.env with your keys (not committed)."
}

if (Test-Path $venvActivate) {
  . $venvActivate
  Write-Host "Activated venv."
} else {
  Write-Host "No venv found. Create it with: python -m venv .venv"
}
