param(
    [string]$QQ = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$NapCatRoot = Join-Path $Root ".tools\napcat-onekey-clean\NapCat.44498.Shell"
$Launcher = Join-Path $NapCatRoot "NapCatWinBootMain.exe"
$Hook = Join-Path $NapCatRoot "NapCatWinBootHook.dll"
$QQExe = Join-Path $NapCatRoot "QQ.exe"
$Main = Join-Path $NapCatRoot "napcat.mjs"
$Load = Join-Path $NapCatRoot "loadNapCat.js"
$Patch = Join-Path $NapCatRoot "qqnt.json"

foreach ($Path in @($NapCatRoot, $Launcher, $Hook, $QQExe, $Main, $Patch)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing NapCat file: $Path"
    }
}

$MainUriPath = ($Main -replace "\\", "/")
Set-Content -LiteralPath $Load -Encoding UTF8 -Value "(async () => {await import(""file:///$MainUriPath"")})()"

$env:NAPCAT_PATCH_PACKAGE = $Patch
$env:NAPCAT_LOAD_PATH = $Load
$env:NAPCAT_INJECT_PATH = $Hook
$env:NAPCAT_LAUNCHER_PATH = $Launcher
$env:NAPCAT_MAIN_PATH = $Main

$ArgsList = @($QQExe, $Hook)
if ($QQ) {
    $ArgsList += @("-q", $QQ)
}

Write-Host "Starting NapCat OneBot..."
Write-Host "NapCatRoot: $NapCatRoot"
Write-Host "OneBot API: http://127.0.0.1:3000"
Write-Host "Event POST: http://127.0.0.1:7800/api/qq/onebot"

Start-Process -FilePath $Launcher -ArgumentList $ArgsList -WorkingDirectory $NapCatRoot
