param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigLoader = Join-Path $ProjectRoot "scripts\load-model-config.ps1"
. $ConfigLoader -ProjectRoot $ProjectRoot
$env:HF_HUB_OFFLINE = "1"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Not installed. Run SPEAKBRIDGE.bat and choose first-time setup first." }

$RunDir = Join-Path $ProjectRoot ".run"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Test-LocalUrl([string]$Url) {
    try {
        $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1
        return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
    } catch {
        return $false
    }
}

$StartupMutex = [System.Threading.Mutex]::new($false, "Local\SpeakBridge.Startup")
$StartupLockAcquired = $false
try {
    try {
        $StartupLockAcquired = $StartupMutex.WaitOne([TimeSpan]::FromSeconds(120))
    } catch [System.Threading.AbandonedMutexException] {
        $StartupLockAcquired = $true
    }
    if (-not $StartupLockAcquired) {
        throw "Another SpeakBridge launcher is still starting. Please try again."
    }

$LlamaCommand = Get-Command "llama-server.exe" -ErrorAction SilentlyContinue
if (-not $LlamaCommand) {
    throw "Thieu llama.cpp. Cai bang lenh: winget install ggml.llamacpp"
}
$HyModel = $SpeakBridgeModelConfig.hy_mt2_model
if (-not (Test-Path -LiteralPath $HyModel)) {
    throw "Thieu model dich Hy-MT2: $HyModel"
}

if (-not (Test-LocalUrl "http://127.0.0.1:8766/health")) {
    $LlmOut = Join-Path $RunDir "llm.stdout.log"
    $LlmErr = Join-Path $RunDir "llm.stderr.log"
    $LlmProcess = Start-Process -FilePath $LlamaCommand.Source `
        -ArgumentList @("-m", $HyModel, "--alias", "hy-mt2-7b", "--host", "127.0.0.1", "--port", "8766", "--device", "Vulkan0", "-ngl", "all", "-c", "3072", "--parallel", "1", "--no-webui", "--jinja") `
        -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $LlmOut -RedirectStandardError $LlmErr -PassThru
    Set-Content -LiteralPath (Join-Path $RunDir "llm.pid") -Value $LlmProcess.Id
}

if (-not (Test-LocalUrl "http://127.0.0.1:8765/health")) {
    $BackendOut = Join-Path $RunDir "backend.stdout.log"
    $BackendErr = Join-Path $RunDir "backend.stderr.log"
    Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", "8765") `
        -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr | Out-Null
}

if (-not (Test-LocalUrl "http://127.0.0.1:3000/")) {
    $FrontendOut = Join-Path $RunDir "frontend.stdout.log"
    $FrontendErr = Join-Path $RunDir "frontend.stderr.log"
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "start") `
        -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendOut -RedirectStandardError $FrontendErr | Out-Null
}

$HotkeyPidFile = Join-Path $RunDir "hotkey.pid"
$HotkeyRunning = $false
if (Test-Path -LiteralPath $HotkeyPidFile) {
    $ExistingHotkeyPid = [int](Get-Content -LiteralPath $HotkeyPidFile)
    $HotkeyRunning = $null -ne (Get-Process -Id $ExistingHotkeyPid -ErrorAction SilentlyContinue)
}
if (-not $HotkeyRunning) {
    $HotkeyExe = Join-Path $ProjectRoot "desktop\dist\SpeakBridgeHotkey.exe"
    $HotkeyScript = Join-Path $ProjectRoot "desktop\hotkey_helper.py"
    if (Test-Path -LiteralPath $HotkeyExe) {
        $HotkeyProcess = Start-Process -FilePath $HotkeyExe -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    } else {
        $HotkeyProcess = Start-Process -FilePath $PythonExe -ArgumentList @($HotkeyScript) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    }
    Set-Content -LiteralPath $HotkeyPidFile -Value $HotkeyProcess.Id
}

$BackendReady = $false
$FrontendReady = $false
for ($Attempt = 0; $Attempt -lt 90; $Attempt++) {
    $BackendReady = Test-LocalUrl "http://127.0.0.1:8765/health"
    $FrontendReady = Test-LocalUrl "http://127.0.0.1:3000/"
    if ($BackendReady -and $FrontendReady) { break }
    Start-Sleep -Milliseconds 500
}

if (-not $BackendReady -or -not $FrontendReady) {
    Write-Host "Backend ready: $BackendReady; Frontend ready: $FrontendReady" -ForegroundColor Red
    foreach ($LogName in @("backend.stderr.log", "frontend.stderr.log")) {
        $LogPath = Join-Path $RunDir $LogName
        if (Test-Path -LiteralPath $LogPath) {
            Write-Host "`n--- $LogName ---" -ForegroundColor Yellow
            Get-Content -LiteralPath $LogPath -Tail 30
        }
    }
    throw "SpeakBridge khong khoi dong day du. Xem log trong thu muc .run"
}

$BackendOwner = Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
$FrontendOwner = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
$LlmOwner = Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($BackendOwner) { Set-Content -LiteralPath (Join-Path $RunDir "backend.pid") -Value $BackendOwner }
if ($FrontendOwner) { Set-Content -LiteralPath (Join-Path $RunDir "frontend.pid") -Value $FrontendOwner }
if ($LlmOwner) { Set-Content -LiteralPath (Join-Path $RunDir "llm.pid") -Value $LlmOwner }

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:3000/"
}
Write-Host "SpeakBridge dang chay tai http://127.0.0.1:3000/" -ForegroundColor Green
Write-Host "Voice Typing: giu Ctrl+Alt+Space de noi, tha ra de nhap chu." -ForegroundColor Green
Write-Host "Stop the app from the SPEAKBRIDGE.bat menu"
} finally {
    if ($StartupLockAcquired) {
        $StartupMutex.ReleaseMutex()
    }
    $StartupMutex.Dispose()
}
