$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigLoader = Join-Path $ProjectRoot "scripts\load-model-config.ps1"
. $ConfigLoader -ProjectRoot $ProjectRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Hay chay install.ps1 truoc." }
Set-Location -LiteralPath $ProjectRoot
& $PythonExe -m backend.warmup
