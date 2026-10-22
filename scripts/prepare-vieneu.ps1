param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location -LiteralPath $root
. (Join-Path $PSScriptRoot 'load-model-config.ps1') -ProjectRoot $root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:HF_HUB_DISABLE_SYMLINKS = '1'
$env:HF_HUB_OFFLINE = if ($Offline) { '1' } else { '0' }
$python = Join-Path $root 'runtime\vieneu\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if ($Offline) { throw 'VieNeu isolated runtime is missing.' }
    & (Join-Path $root '.venv\Scripts\python.exe') -m venv (Join-Path $root 'runtime\vieneu\.venv')
    if ($LASTEXITCODE -ne 0) { throw 'VieNeu venv creation failed.' }
}
if (-not $Offline) {
    & $python -m pip install 'vieneu==3.8.3' --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'VieNeu SDK installation failed.' }
}
# Existing linked ONNX external-data files can fail newer ORT path validation.
# Materialize only links under our dedicated cache; keep their blobs recoverable.
$modelRoot = [IO.Path]::GetFullPath((Join-Path $root 'models\vieneu-v3-turbo'))
$cache = Join-Path $modelRoot 'huggingface\hub'
if (Test-Path -LiteralPath $cache) {
    foreach ($item in (Get-ChildItem -LiteralPath $cache -Recurse -File | Where-Object LinkType -eq 'SymbolicLink')) {
        $target = [IO.Path]::GetFullPath($item.FullName)
        if (-not $target.StartsWith($modelRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe cache path.' }
        $temporary = $target + '.materialized'
        [IO.File]::Copy($target, $temporary, $false)
        if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $temporary).Hash) { throw 'Cache copy hash mismatch.' }
        Remove-Item -LiteralPath $target -Force
        Move-Item -LiteralPath $temporary -Destination $target
    }
}
& $python (Join-Path $PSScriptRoot 'prepare-vieneu.py')
if ($LASTEXITCODE -ne 0) { throw 'VieNeu model verification failed; not activated.' }
