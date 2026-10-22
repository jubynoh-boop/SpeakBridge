$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir = Join-Path $ProjectRoot ".run"
. (Join-Path $ProjectRoot 'scripts\process-ownership.ps1')
$Refused = $false

foreach ($Name in @("hotkey", "backend", "frontend", "llm")) {
    $PidFile = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $PidFile)) { continue }
    try {
        $ProcessId = [int](Get-Content -LiteralPath $PidFile)
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $PidFile -Force
            continue
        }
        $Process = Get-SpeakBridgeOwnedProcess -ProcessId $ProcessId -Role $Name -ProjectRoot $ProjectRoot
        $IdentityPath = Join-Path $RunDir "$Name.process.json"
        if ($Process -and (Test-Path -LiteralPath $IdentityPath)) {
            $Identity = Get-Content -LiteralPath $IdentityPath -Raw | ConvertFrom-Json
            if (-not (Test-SpeakBridgeProcessIdentity -Process $Process -Identity $Identity -Role $Name)) { $Process = $null }
        }
        if (-not $Process) {
            $Refused = $true
            Write-Warning "Refusing to stop unverified $Name PID $ProcessId. No unrelated process was stopped."
            continue
        }
        # A PyInstaller bootloader / venv redirector is also part of this
        # installation, but only if its current path and role verify independently.
        $Parent = Get-SpeakBridgeOwnedProcess -ProcessId $Process.ParentProcessId -Role $Name -ProjectRoot $ProjectRoot
        Stop-Process -Id $ProcessId -ErrorAction Stop
        if ($Parent -and $Parent.CreationDate -le $Process.CreationDate) {
            Stop-Process -Id $Parent.ProcessId -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $PidFile -Force
        if (Test-Path -LiteralPath $IdentityPath) { Remove-Item -LiteralPath $IdentityPath -Force }
    } catch {
        $Refused = $true
        Write-Warning "Could not safely stop $Name`: $_"
    }
}

if ($Refused) { throw 'Some processes could not be verified/stopped. See warnings above.' }
Write-Host "SpeakBridge da dung." -ForegroundColor Green
