@echo off
setlocal enabledelayedexpansion

REM Load variables from .env into this cmd session (if present)
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    set "key=%%A"
    if not "!key!"=="" if "!key:~0,1!" NEQ "#" set "%%A=%%B"
  )
) else (
  echo No .env found. Create C:\Projects\InstantPriceMatch\.env with your keys (not committed).
)

REM Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
  call .\.venv\Scripts\activate.bat
) else (
  echo No venv found. Create it with: python -m venv .venv
)

endlocal
