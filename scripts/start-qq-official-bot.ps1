param(
  [int]$DaemonPort = 7800,
  [string]$CommandPrefix = "/mew",
  [string]$AppId = "",
  [string]$AppSecret = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Split-Path -Parent $PSScriptRoot
$PythonDir = Join-Path $Root "MozilCode-python"
$EnvFile = Join-Path $Root ".mewcode\qq-official.env.ps1"
$Log = Join-Path $Root ".daemon.qq-official.log"
$Err = Join-Path $Root ".daemon.qq-official.err.log"

if (Test-Path $EnvFile) {
  . $EnvFile
}

if ($AppId) {
  $env:MOZILCODE_QQ_OFFICIAL_APP_ID = $AppId
}
if ($AppSecret) {
  $env:MOZILCODE_QQ_OFFICIAL_APP_SECRET = $AppSecret
}

if (-not $env:MOZILCODE_QQ_OFFICIAL_APP_ID -or -not $env:MOZILCODE_QQ_OFFICIAL_APP_SECRET) {
  throw "QQ official AppID/AppSecret are missing. Put them in $EnvFile or pass -AppId/-AppSecret."
}

$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -eq $DaemonPort }
foreach ($listener in $listeners) {
  try {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 500
  } catch {
    Write-Warning "Failed to stop process $($listener.OwningProcess) on port ${DaemonPort}: $_"
  }
}

$env:MOZILCODE_QQ_OFFICIAL_ENABLED = "1"
$env:MOZILCODE_QQ_COMMAND_PREFIX = $CommandPrefix
if (-not $env:MOZILCODE_QQ_OFFICIAL_INTENTS) {
  $env:MOZILCODE_QQ_OFFICIAL_INTENTS = [string]([math]::Pow(2, 25))
}

$args = @(
  "run",
  "python",
  (Join-Path $Root "scripts\run_mozilcode_daemon.py"),
  "--host", "127.0.0.1",
  "--port", "$DaemonPort",
  "--work-dir", $Root
)

$proc = Start-Process -FilePath "uv.exe" `
  -WorkingDirectory $PythonDir `
  -ArgumentList $args `
  -RedirectStandardOutput $Log `
  -RedirectStandardError $Err `
  -WindowStyle Hidden `
  -PassThru

Start-Sleep -Seconds 2

$status = $null
$card = $null
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
  try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/api/qq/official/status" -TimeoutSec 5
    $card = Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/.well-known/agent-card.json" -TimeoutSec 5
    break
  } catch {
    Start-Sleep -Seconds 1
  }
}

if ($status -and $card) {
  Write-Host "MozilCode official QQ Bot daemon started."
  Write-Host "PID: $($proc.Id)"
  Write-Host "Agent card: http://127.0.0.1:$DaemonPort/.well-known/agent-card.json"
  Write-Host "QQ official status: http://127.0.0.1:$DaemonPort/api/qq/official/status"
  Write-Host "Command prefix: $CommandPrefix"
  Write-Host "Configured: $($status.configured)"
  Write-Host "Gateway running: $($status.running)"
  Write-Host "Logs: $Log"
  Write-Host "Errors: $Err"
} else {
  Write-Host "Daemon process started, but health check did not pass in time."
  Write-Host "PID: $($proc.Id)"
  Write-Host "Logs: $Log"
  Write-Host "Errors: $Err"
  exit 1
}
