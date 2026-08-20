$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Run SPEAKBRIDGE.bat and choose first-time setup first." }

Set-Location -LiteralPath $ProjectRoot
$env:PYINSTALLER_CONFIG_DIR = Join-Path $ProjectRoot "desktop\.pyinstaller-cache"
$env:TEMP = Join-Path $env:PYINSTALLER_CONFIG_DIR "tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name SpeakBridgeHotkey `
    --exclude-module numpy `
    --distpath desktop\dist `
    --workpath desktop\build `
    --specpath desktop `
    --collect-all pyaudiowpatch `
    desktop\hotkey_helper.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host "Created desktop\dist\SpeakBridgeHotkey.exe" -ForegroundColor Green
