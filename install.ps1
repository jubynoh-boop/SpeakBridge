$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigLoader = Join-Path $ProjectRoot "scripts\load-model-config.ps1"
. $ConfigLoader -ProjectRoot $ProjectRoot
Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command "py.exe" -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 is required. Install it from python.org, then run this installer again."
}
if (-not (Get-Command "node.exe" -ErrorAction SilentlyContinue)) {
    throw "Node.js 22 or newer is required. Install it from nodejs.org, then run this installer again."
}
if (-not (Get-Command "npm.cmd" -ErrorAction SilentlyContinue)) {
    throw "npm is required and should be installed with Node.js."
}

$NodeMajor = [int]((& node.exe --version).TrimStart("v").Split(".")[0])
if ($NodeMajor -lt 22) { throw "Node.js 22 or newer is required." }

Write-Host "[1/5] Tao moi truong Python..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
}
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Write-Host "[2/5] Cai PyTorch CUDA..." -ForegroundColor Cyan
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

Write-Host "[3/5] Cai speech engine..." -ForegroundColor Cyan
& $PythonExe -m pip install -r backend\requirements.txt

Write-Host "[4/5] Cai va build giao dien..." -ForegroundColor Cyan
& npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

Write-Host "[5/5] Cai llama.cpp CUDA tren o F..." -ForegroundColor Cyan
& (Join-Path $ProjectRoot "scripts\install-llama-cuda.ps1") -ProjectRoot $ProjectRoot

Write-Host "Hoan tat. Chay .\prepare-models.ps1 mot lan, sau do .\start.ps1" -ForegroundColor Green
