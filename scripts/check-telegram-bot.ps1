param(
  [int]$DaemonPort = 7800
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".mewcode\telegram.env.ps1"

if (Test-Path $EnvFile) {
  . $EnvFile
}

Write-Host "== MozilCode Daemon =="
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/api/telegram/status" -TimeoutSec 5 |
    Select-Object enabled, configured, running, session_ready, bot_username, last_error |
    Format-List
} catch {
  $Message = $_.Exception.Message
  if ($env:MOZILCODE_TELEGRAM_BOT_TOKEN) {
    $Message = $Message.Replace($env:MOZILCODE_TELEGRAM_BOT_TOKEN, "<redacted>")
  }
  Write-Host "FAILED: $Message"
}

Write-Host "`n== Telegram Bot API =="
try {
  if (-not $env:MOZILCODE_TELEGRAM_BOT_TOKEN) {
    throw "Bot token missing"
  }
  $me = Invoke-RestMethod `
    -Uri "https://api.telegram.org/bot$($env:MOZILCODE_TELEGRAM_BOT_TOKEN)/getMe" `
    -Method Post `
    -ContentType "application/json" `
    -Body "{}" `
    -TimeoutSec 15
  if ($me.ok) {
    Write-Host "OK: bot username=$($me.result.username)"
  } else {
    Write-Host "FAILED: Telegram returned ok=false"
  }
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}
