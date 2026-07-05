param(
  [int]$DaemonPort = 7800,
  [int]$OneBotPort = 3000
)

$ErrorActionPreference = "Continue"

Write-Host "== Ports =="
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in @($DaemonPort, $OneBotPort) } |
  Select-Object LocalAddress, LocalPort, OwningProcess |
  Format-Table

Write-Host "`n== MozilCode A2A =="
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/.well-known/agent-card.json" -TimeoutSec 5 |
    Select-Object name, url, preferredTransport |
    Format-List
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host "`n== QQ Webhook =="
try {
  Invoke-RestMethod `
    -Uri "http://127.0.0.1:$DaemonPort/api/qq/onebot" `
    -Method Post `
    -ContentType "application/json" `
    -Body '{"post_type":"notice"}' `
    -TimeoutSec 5 |
    ConvertTo-Json -Depth 5
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host "`n== OneBot API =="
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:$OneBotPort/get_status" -TimeoutSec 5 |
    ConvertTo-Json -Depth 5
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}
