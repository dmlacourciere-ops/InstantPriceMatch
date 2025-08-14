param(
  [Parameter(Mandatory = $true)][string]$ip,
  [int]$port = 4747
)

function Say([string]$msg, [ConsoleColor]$c = "Gray") {
  $old = $Host.UI.RawUI.ForegroundColor
  $Host.UI.RawUI.ForegroundColor = $c
  Write-Host $msg
  $Host.UI.RawUI.ForegroundColor = $old
}

Say "Testing reachability for DroidCam at $($ip):$port/video" "Cyan"

# 1) Ping
try {
  $ok = Test-Connection -ComputerName $ip -Count 1 -Quiet
  if ($ok) { Say "Ping OK" "Green" } else { Say "Ping failed (device offline or ICMP blocked)" "Yellow" }
} catch {
  Say ("Ping error: {0}" -f $_.Exception.Message) "Yellow"
}

# 2) TCP port test
try {
  $tnc = Test-NetConnection -ComputerName $ip -Port $port
  if ($tnc.TcpTestSucceeded) { Say "TCP test: port $port open" "Green" } else { Say "TCP test: port $port closed" "Yellow" }
} catch {
  Say ("TCP test error: {0}" -f $_.Exception.Message) "Yellow"
}

# 3) HTTP probe
$probeUrl = "http://$($ip):$port/video"
try {
  $resp = Invoke-WebRequest -Uri $probeUrl -Method Head -TimeoutSec 4 -UseBasicParsing
  Say ("HTTP HEAD {0} OK" -f $resp.StatusCode) "Green"
} catch {
  try {
    $resp = Invoke-WebRequest -Uri $probeUrl -Method Get -TimeoutSec 5 -UseBasicParsing
    Say ("HTTP GET {0} OK (HEAD blocked)" -f $resp.StatusCode) "Green"
  } catch {
    Say "HTTP probe failed to $probeUrl" "Red"
    Say "Tips: open DroidCam (WiFi), verify IP/port on phone, same Wi‑Fi, and allow Python through Windows Firewall." "Yellow"
  }
}