param(
  [int]$DaemonPort = 7800,
  [string]$CommandPrefix = "/mew",
  [string]$BotToken = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Split-Path -Parent $PSScriptRoot
$PythonDir = Join-Path $Root "MozilCode-python"
$EnvFile = Join-Path $Root ".mewcode\telegram.env.ps1"
$Log = Join-Path $Root ".daemon.telegram.log"
$Err = Join-Path $Root ".daemon.telegram.err.log"

if (Test-Path $EnvFile) {
  . $EnvFile
}

if ($BotToken) {
  $env:MOZILCODE_TELEGRAM_BOT_TOKEN = $BotToken
}

if (-not $env:MOZILCODE_TELEGRAM_BOT_TOKEN) {
  throw "Telegram Bot token is missing. Put it in $EnvFile or pass -BotToken."
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

$env:MOZILCODE_TELEGRAM_ENABLED = "1"
$env:MOZILCODE_TELEGRAM_COMMAND_PREFIX = $CommandPrefix

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
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
  try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/api/telegram/status" -TimeoutSec 5
    break
  } catch {
    Start-Sleep -Seconds 1
  }
}

if ($status) {
  Write-Host "MozilCode Telegram Bot daemon started."
  Write-Host "PID: $($proc.Id)"
  Write-Host "Agent card: http://127.0.0.1:$DaemonPort/.well-known/agent-card.json"
  Write-Host "Telegram status: http://127.0.0.1:$DaemonPort/api/telegram/status"
  Write-Host "Command prefix: $CommandPrefix"
  Write-Host "Configured: $($status.configured)"
  Write-Host "Polling running: $($status.running)"
  Write-Host "Logs: $Log"
  Write-Host "Errors: $Err"
} else {
  Write-Host "Daemon process started, but health check did not pass in time."
  Write-Host "PID: $($proc.Id)"
  Write-Host "Logs: $Log"
  Write-Host "Errors: $Err"
  exit 1
}
