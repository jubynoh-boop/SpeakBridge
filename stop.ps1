$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir = Join-Path $ProjectRoot ".run"

# PyInstaller one-file uses a short-lived bootloader plus the application
# process. Stop both so the EXE can be rebuilt or upgraded cleanly.
Get-Process -Name "SpeakBridgeHotkey" -ErrorAction SilentlyContinue | Stop-Process -Force

foreach ($Name in @("hotkey", "backend", "frontend", "llm")) {
    $PidFile = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $PidFile)) { continue }
    $ProcessId = [int](Get-Content -LiteralPath $PidFile)
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($Process) { Stop-Process -Id $ProcessId }
    Remove-Item -LiteralPath $PidFile -Force
}

Write-Host "SpeakBridge da dung." -ForegroundColor Green
