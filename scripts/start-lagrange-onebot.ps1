$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $Root ".tools\lagrange-onebot\Lagrange.OneBot\bin\Release\net9.0\win-x64\publish\Lagrange.OneBot.exe"
$RunDir = Join-Path $Root ".mewcode\lagrange"

if (!(Test-Path $Exe)) {
  throw "Lagrange.OneBot.exe not found: $Exe"
}

if (!(Test-Path (Join-Path $RunDir "appsettings.json"))) {
  throw "Lagrange appsettings.json not found: $RunDir"
}

Write-Host "Starting Lagrange.OneBot..."
Write-Host "Run dir: $RunDir"
Write-Host "HTTP API: http://127.0.0.1:3000"
Write-Host "Event post: http://127.0.0.1:7800/api/qq/onebot"
Write-Host "Scan the QR code in the new console window if this is the first login."

$Command = "cd /d `"$RunDir`" && `"$Exe`""
$WindowsTerminal = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($WindowsTerminal) {
  Start-Process -FilePath $WindowsTerminal.Source -ArgumentList @("cmd", "/k", $Command)
} else {
  Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $Command)
}
