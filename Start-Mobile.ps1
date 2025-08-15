# Start-Mobile.ps1
# Opens Streamlit in one PowerShell, then prints a public HTTPS tunnel link.

Set-Location "C:\Projects\InstantPriceMatch"

# Load your venv + API key like your usual dev script
.\Activate-Dev.ps1 | Out-Null

# 1) Streamlit in a new window that stays open
Start-Process powershell -ArgumentList '-NoExit','-Command','streamlit run ui_price_match_mobile.py'

# 2) Give Streamlit a moment to start
Start-Sleep -Seconds 2

# 3) Launch cloudflared (prints the https://… link here)
& "C:\Tools\cloudflared\cloudflared.exe" tunnel --url http://localhost:8501
