param(
  [int]$DaemonPort = 7800,
  [int]$OneBotPort = 3000,
  [string]$CommandPrefix = "/mew"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PythonDir = Join-Path $Root "MozilCode-python"
$Log = Join-Path $Root ".daemon.qq.log"
$Err = Join-Path $Root ".daemon.qq.err.log"

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

$env:MOZILCODE_QQ_ONEBOT_API_URL = "http://127.0.0.1:$OneBotPort"
$env:MOZILCODE_QQ_COMMAND_PREFIX = $CommandPrefix
$env:MOZILCODE_QQ_REPLY_MODE = "auto"

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

Start-Sleep -Seconds 3

try {
  $card = Invoke-RestMethod -Uri "http://127.0.0.1:$DaemonPort/.well-known/agent-card.json" -TimeoutSec 5
  Write-Host "MozilCode QQ A2A daemon started."
  Write-Host "PID: $($proc.Id)"
  Write-Host "Agent card: http://127.0.0.1:$DaemonPort/.well-known/agent-card.json"
  Write-Host "QQ webhook: http://127.0.0.1:$DaemonPort/api/qq/onebot"
  Write-Host "OneBot API: http://127.0.0.1:$OneBotPort"
  Write-Host "Command prefix: $CommandPrefix"
} catch {
  Write-Error "Daemon failed to start. Check $Err"
}
