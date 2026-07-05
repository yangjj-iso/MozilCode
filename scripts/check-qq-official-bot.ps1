param(
  [int]$DaemonPort = 7800
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".mewcode\qq-official.env.ps1"

if (Test-Path $EnvFile) {
  . $EnvFile
}

Write-Host "== MozilCode Daemon =="
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/api/qq/official/status" -TimeoutSec 5 |
    Select-Object enabled, configured, running, session_ready, bot_username, last_error |
    Format-List
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host "`n== Official QQ Token =="
try {
  if (-not $env:MOZILCODE_QQ_OFFICIAL_APP_ID -or -not $env:MOZILCODE_QQ_OFFICIAL_APP_SECRET) {
    throw "AppID/AppSecret missing"
  }
  $body = @{
    appId = $env:MOZILCODE_QQ_OFFICIAL_APP_ID
    clientSecret = $env:MOZILCODE_QQ_OFFICIAL_APP_SECRET
  } | ConvertTo-Json
  $token = Invoke-RestMethod `
    -Uri "https://bots.qq.com/app/getAppAccessToken" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body `
    -TimeoutSec 15
  if ($token.access_token) {
    Write-Host "OK: access token acquired; expires_in=$($token.expires_in)"
  } else {
    Write-Host "FAILED: access_token missing"
  }
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host "`n== Official QQ Gateway URL =="
try {
  if (-not $token.access_token) {
    throw "No access token"
  }
  $gateway = Invoke-RestMethod `
    -Uri "https://api.sgroup.qq.com/gateway" `
    -Headers @{ Authorization = "QQBot $($token.access_token)" } `
    -TimeoutSec 15
  if ($gateway.url) {
    Write-Host "OK: gateway URL available"
  } else {
    Write-Host "FAILED: gateway url missing"
  }
} catch {
  Write-Host "FAILED: $($_.Exception.Message)"
}
