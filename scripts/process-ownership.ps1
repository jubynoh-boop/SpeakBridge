# Read-only ownership checks shared by launch and shutdown. Never trust a PID
# file alone: Windows can reuse it after an application exits.
function Get-SpeakBridgeOwnedProcess {
    param([int]$ProcessId, [string]$Role, [string]$ProjectRoot)
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    if (-not $Process) { return $null }
    $Root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $Command = [string]$Process.CommandLine
    $Executable = [string]$Process.ExecutablePath
    $Owned = $false
    $Parent = $null
    switch ($Role) {
        'hotkey' {
            $Owned = $Executable -ieq (Join-Path $Root 'SpeakBridgeHotkey.exe') -or
                     $Executable -ieq (Join-Path $Root 'desktop\dist\SpeakBridgeHotkey.exe') -or
                     $Command.IndexOf((Join-Path $Root 'desktop\hotkey_helper.py'), [StringComparison]::OrdinalIgnoreCase) -ge 0
        }
        'frontend' {
            $Owned = $Command.IndexOf((Join-Path $Root 'node_modules'), [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $Command -match 'vinext.*\bstart\b'
        }
        'backend' {
            if ($Command -match 'uvicorn\s+backend\.server:app' -and $Command -match '--port\s+8765\b') {
                $Owned = $Executable -ieq (Join-Path $Root '.venv\Scripts\python.exe')
                if (-not $Owned) {
                    $Parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.ParentProcessId)" -ErrorAction Stop
                    $Owned = $Parent -and $Parent.ExecutablePath -ieq (Join-Path $Root '.venv\Scripts\python.exe') -and $Parent.CommandLine -match 'uvicorn\s+backend\.server:app'
                }
            }
        }
        'llm' {
            $ConfigPath = Join-Path $Root 'config\models.local.json'
            $LlamaPath = Join-Path $Root 'runtime\llama-cuda\llama-server.exe'
            if (Test-Path -LiteralPath $ConfigPath) {
                $Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
                if ($Config.llama_server) {
                    $LlamaPath = if ([IO.Path]::IsPathRooted($Config.llama_server)) { [IO.Path]::GetFullPath($Config.llama_server) } else { [IO.Path]::GetFullPath((Join-Path $Root $Config.llama_server)) }
                }
            }
            $Owned = $Executable -ieq $LlamaPath -and $Command -match '--alias\s+hy-mt2-7b\b' -and $Command -match '--port\s+8766\b'
        }
    }
    if (-not $Owned) { return $null }
    return $Process
}

function Save-SpeakBridgeProcessIdentity {
    param([int]$ProcessId, [string]$Role, [string]$ProjectRoot)
    try {
        $Process = Get-SpeakBridgeOwnedProcess -ProcessId $ProcessId -Role $Role -ProjectRoot $ProjectRoot
        if ($Process) {
            @{ pid = $ProcessId; role = $Role; created_utc = $Process.CreationDate.ToUniversalTime().ToString('o') } |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProjectRoot ".run\$Role.process.json") -Encoding UTF8
        } else { Write-Warning "Not recording unverified $Role process $ProcessId." }
    } catch { Write-Warning "Cannot record $Role process identity: $_" }
}

function Test-SpeakBridgeProcessIdentity {
    param($Process, $Identity, [string]$Role)
    try {
        # PowerShell 5 returns ISO dates as strings; PowerShell 7 may return
        # DateTime objects. Compare instants, not their display strings.
        $SavedTicks = ([DateTimeOffset]$Identity.created_utc).UtcDateTime.Ticks
        return $Identity.pid -eq $Process.ProcessId -and $Identity.role -eq $Role -and
               $SavedTicks -eq $Process.CreationDate.ToUniversalTime().Ticks
    } catch { return $false }
}
