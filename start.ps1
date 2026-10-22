param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigLoader = Join-Path $ProjectRoot "scripts\load-model-config.ps1"
. $ConfigLoader -ProjectRoot $ProjectRoot
. (Join-Path $ProjectRoot 'scripts\process-ownership.ps1')
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

function Assert-ReusableService([string]$Role, [int]$Port) {
    $Owner = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
    if ($Owner -and -not (Get-SpeakBridgeOwnedProcess -ProcessId $Owner -Role $Role -ProjectRoot $ProjectRoot)) {
        throw "Port $Port belongs to another application/installation. It was not stopped. Close it or resolve the port conflict first."
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

Assert-ReusableService 'backend' 8765
Assert-ReusableService 'frontend' 3000
Assert-ReusableService 'llm' 8766

$ConfiguredLlamaServer = $SpeakBridgeModelConfig.llama_server
$LlamaServerExe = if ($ConfiguredLlamaServer -and (Test-Path -LiteralPath $ConfiguredLlamaServer)) {
    $ConfiguredLlamaServer
} else {
    $LlamaCommand = Get-Command "llama-server.exe" -ErrorAction SilentlyContinue
    if ($LlamaCommand) { $LlamaCommand.Source } else { $null }
}
if (-not $LlamaServerExe) {
    throw "Thieu llama.cpp CUDA tai: $ConfiguredLlamaServer"
}
$LlamaDevice = if ($SpeakBridgeModelConfig.llama_device) { [string]$SpeakBridgeModelConfig.llama_device } else { "CUDA0" }
$HyModel = $SpeakBridgeModelConfig.hy_mt2_model
if (-not (Test-Path -LiteralPath $HyModel)) {
    throw "Thieu model dich Hy-MT2: $HyModel"
}

if (-not (Test-LocalUrl "http://127.0.0.1:8766/health")) {
    $LlmOut = Join-Path $RunDir "llm.stdout.log"
    $LlmErr = Join-Path $RunDir "llm.stderr.log"
    $LlmProcess = Start-Process -FilePath $LlamaServerExe `
        -ArgumentList @("-m", "`"$HyModel`"", "--alias", "hy-mt2-7b", "--host", "127.0.0.1", "--port", "8766", "--device", $LlamaDevice, "-ngl", "all", "-c", "3072", "--parallel", "1", "--no-webui", "--jinja") `
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
if (Test-Path -LiteralPath (Join-Path $RunDir "hotkey-status.json")) {
    try {
        $HelperState = Get-Content -LiteralPath (Join-Path $RunDir "hotkey-status.json") -Raw | ConvertFrom-Json
        $ExistingHotkeyPid = [int]$HelperState.pid
        $HeartbeatAge = ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0) - [double]$HelperState.updated_at
        $HotkeyRunning = $HelperState.listener_alive -and $HeartbeatAge -ge 0 -and $HeartbeatAge -lt 8 -and $null -ne (Get-Process -Id $ExistingHotkeyPid -ErrorAction SilentlyContinue)
        if ($HotkeyRunning) { Set-Content -LiteralPath $HotkeyPidFile -Value $ExistingHotkeyPid }
    } catch { $HotkeyRunning = $false }
}
if (-not $HotkeyRunning) {
    $HotkeyExe = Join-Path $ProjectRoot "desktop\dist\SpeakBridgeHotkey.exe"
    $HotkeyScript = Join-Path $ProjectRoot "desktop\hotkey_helper.py"
    if ((Test-Path -LiteralPath (Join-Path $ProjectRoot ".git")) -and (Test-Path -LiteralPath $HotkeyScript)) {
        # Source checkout: use the current helper code without requiring a rebuilt EXE.
        $HotkeyProcess = Start-Process -FilePath $PythonExe -ArgumentList @("`"$HotkeyScript`"") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    } elseif (Test-Path -LiteralPath $HotkeyExe) {
        $HotkeyProcess = Start-Process -FilePath $HotkeyExe -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    } else {
        $HotkeyProcess = Start-Process -FilePath $PythonExe -ArgumentList @("`"$HotkeyScript`"") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    }
    # A one-file EXE has a bootloader PID and an actual helper PID. Use the
    # helper's heartbeat rather than the launcher/bootloader PID.
    for ($HelperAttempt = 0; $HelperAttempt -lt 40; $HelperAttempt++) {
        try {
            $HelperState = Get-Content -LiteralPath (Join-Path $RunDir "hotkey-status.json") -Raw | ConvertFrom-Json
            $HeartbeatAge = ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0) - [double]$HelperState.updated_at
            if ($HelperState.listener_alive -and $HeartbeatAge -ge 0 -and $HeartbeatAge -lt 8 -and $null -ne (Get-Process -Id ([int]$HelperState.pid) -ErrorAction SilentlyContinue)) {
                Set-Content -LiteralPath $HotkeyPidFile -Value $HelperState.pid
                $HotkeyRunning = $true
                break
            }
        } catch { }
        Start-Sleep -Milliseconds 250
    }
    if (-not $HotkeyRunning) { throw "Hotkey helper did not start. See .run\hotkey.log" }
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
foreach ($Role in @('backend', 'frontend', 'llm', 'hotkey')) {
    $RolePidPath = Join-Path $RunDir "$Role.pid"
    if (Test-Path -LiteralPath $RolePidPath) {
        Save-SpeakBridgeProcessIdentity -ProcessId ([int](Get-Content -LiteralPath $RolePidPath)) -Role $Role -ProjectRoot $ProjectRoot
    }
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:3000/"
}
Write-Host "SpeakBridge dang chay tai http://127.0.0.1:3000/" -ForegroundColor Green
Write-Host "Voice Typing: hold your configured shortcut to speak; release to insert text. See Settings for the current shortcut." -ForegroundColor Green
Write-Host "Stop the app from the SPEAKBRIDGE.bat menu"
} finally {
    if ($StartupLockAcquired) {
        $StartupMutex.ReleaseMutex()
    }
    $StartupMutex.Dispose()
}
