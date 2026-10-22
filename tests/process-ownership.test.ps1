$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $RepositoryRoot 'scripts\process-ownership.ps1')
$MockRoot = 'F:\SpeakBridge Ownership Test'
$script:MockProcesses = @{}
function Get-CimInstance { param($ClassName, $Filter, $ErrorAction) return $script:MockProcesses[[int]($Filter.Split('=')[1])] }
function Assert-Ownership($Role, $Expected) {
    $Result = Get-SpeakBridgeOwnedProcess -ProcessId 42 -Role $Role -ProjectRoot $MockRoot
    if ([bool]$Result -ne $Expected) { throw "Ownership check failed: $Role, expected $Expected" }
}
$script:MockProcesses[42] = [PSCustomObject]@{ ProcessId=42; ParentProcessId=43; ExecutablePath='C:\OtherApp\SpeakBridgeHotkey.exe'; CommandLine='C:\OtherApp\SpeakBridgeHotkey.exe' }
Assert-Ownership 'hotkey' $false
$script:MockProcesses[42].ExecutablePath = Join-Path $MockRoot 'SpeakBridgeHotkey.exe'
Assert-Ownership 'hotkey' $true
$script:MockProcesses[42].ExecutablePath = 'C:\Python\python.exe'
$script:MockProcesses[42].CommandLine = 'python -m uvicorn backend.server:app --port 8765'
$script:MockProcesses[43] = [PSCustomObject]@{ ExecutablePath='C:\OtherApp\.venv\Scripts\python.exe'; CommandLine='python -m uvicorn backend.server:app' }
Assert-Ownership 'backend' $false
$script:MockProcesses[43].ExecutablePath = Join-Path $MockRoot '.venv\Scripts\python.exe'
Assert-Ownership 'backend' $true
$script:MockProcesses[42].CommandLine = 'node C:\OtherApp\node_modules\vinext\dist\cli.js start'
Assert-Ownership 'frontend' $false
$script:MockProcesses[42].CommandLine = 'node "F:\SpeakBridge Ownership Test\node_modules\vinext\dist\cli.js" start'
Assert-Ownership 'frontend' $true
Write-Host 'Process ownership: 6 checks passed (no real processes stopped).'
$CreationTime = [DateTime]::Parse('2026-10-07T12:48:48.8124850Z').ToUniversalTime()
$Process = [PSCustomObject]@{ ProcessId=42; CreationDate=$CreationTime }
$Identity = [PSCustomObject]@{ pid=42; role='backend'; created_utc=$CreationTime.ToString('o') }
if (-not (Test-SpeakBridgeProcessIdentity $Process $Identity 'backend')) { throw 'String date failed' }
$Identity.created_utc = $CreationTime
if (-not (Test-SpeakBridgeProcessIdentity $Process $Identity 'backend')) { throw 'DateTime date failed' }
$Identity.created_utc = $CreationTime.AddSeconds(-1)
if (Test-SpeakBridgeProcessIdentity $Process $Identity 'backend') { throw 'Reused PID accepted' }
$Identity.created_utc = $CreationTime
$Identity.pid = 43
if (Test-SpeakBridgeProcessIdentity $Process $Identity 'backend') { throw 'Wrong PID accepted' }
$Identity.pid = 42
if (Test-SpeakBridgeProcessIdentity $Process $Identity 'hotkey') { throw 'Wrong role accepted' }
Write-Host 'Process identity: 5 checks passed.'
