# Activate-Dev.ps1
# Usage:
#   1) In VS Code Terminal or PowerShell: .\Activate-Dev.ps1
#   2) It activates .venv and loads variables from .env (if present).
#   3) Then you can run: streamlit run ui_app.py

param(
  [switch]$Quiet
)

$ErrorActionPreference = "Stop"

# Always run from the repo root where this script lives
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Activate or create venv
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  . .\.venv\Scripts\Activate.ps1
} else {
  Write-Host "Creating .venv..."
  py -3.13 -m venv .venv
  . .\.venv\Scripts\Activate.ps1
}

# Load .env variables (if present), ignore comments/blank lines
$envPath = ".\.env"
if (Test-Path $envPath) {
  Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    if ($_ -match '^\s*([^=]+?)\s*=\s*(.*)\s*$') {
      $name  = $matches[1].Trim()
      $value = $matches[2]
      # Strip surrounding quotes if present
      if ($value.StartsWith('"') -and $value.EndsWith('"')) { $value = $value.Substring(1, $value.Length-2) }
      if ($value.StartsWith("'") -and $value.EndsWith("'")) { $value = $value.Substring(1, $value.Length-2) }
      Set-Item -Path "Env:$name" -Value $value
      if (-not $Quiet) {
        $tail = if ($value.Length -ge 6) { $value.Substring($value.Length-6) } else { $value }
        Write-Host ("Loaded {0}=***{1}" -f $name,$tail)
      }
    }
  }
} else {
  Write-Host ".env not found (that's OK if you export vars per-session)."
}

Write-Host ""
Write-Host "Dev shell ready."
Write-Host " - Venv :" $env:VIRTUAL_ENV
Write-Host " - Key? :" ("OPENAI_API_KEY set = " + [bool]$env:OPENAI_API_KEY)
Write-Host ""
Write-Host "Run the app:"
Write-Host "  streamlit run ui_app.py"
