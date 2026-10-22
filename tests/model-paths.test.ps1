$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$temporaryRoot = Join-Path $root '.model-cache\temp'
$fixture = [IO.Path]::GetFullPath((Join-Path $temporaryRoot ('model-path-test-' + [guid]::NewGuid().ToString('N'))))
$variables = @('HF_HOME', 'HF_HUB_CACHE', 'HF_XET_CACHE', 'HF_MODULES_CACHE', 'HUGGINGFACE_HUB_CACHE', 'TRANSFORMERS_CACHE', 'PYTORCH_TRANSFORMERS_CACHE', 'PYTORCH_PRETRAINED_BERT_CACHE', 'TORCH_HOME', 'PIP_CACHE_DIR', 'npm_config_cache', 'TEMP', 'TMP', 'XDG_CACHE_HOME', 'UV_CACHE_DIR', 'NUMBA_CACHE_DIR', 'SPEAKBRIDGE_HY_MODEL', 'SPEAKBRIDGE_LLAMA_SERVER', 'SPEAKBRIDGE_LLAMA_DEVICE')
$previous = @{}
foreach ($name in $variables) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
function Assert-Equal($actual, $expected) {
    if ($actual -ne $expected) { throw "Expected '$expected', got '$actual'" }
}
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $fixture 'config') | Out-Null
    $env:TRANSFORMERS_CACHE = 'C:\legacy-cache'
    $env:HUGGINGFACE_HUB_CACHE = 'C:\legacy-hub'
    . (Join-Path $root 'scripts\load-model-config.ps1') -ProjectRoot $fixture
    Assert-Equal $env:HF_HOME (Join-Path $fixture 'models\huggingface')
    Assert-Equal $env:HF_HUB_CACHE (Join-Path $fixture 'models\huggingface\hub')
    Assert-Equal $env:HF_XET_CACHE (Join-Path $fixture 'models\huggingface\xet')
    Assert-Equal $env:UV_CACHE_DIR (Join-Path $fixture '.model-cache\uv')
    Assert-Equal $env:NUMBA_CACHE_DIR (Join-Path $fixture '.model-cache\numba')
    Assert-Equal $env:SPEAKBRIDGE_HY_MODEL (Join-Path $fixture 'models\HY-MT2-7B-Q6_K.gguf')
    Assert-Equal $env:TRANSFORMERS_CACHE $null
    Assert-Equal $env:HUGGINGFACE_HUB_CACHE $null
    Copy-Item -LiteralPath (Join-Path $root 'config\models.example.json') -Destination (Join-Path $fixture 'config\models.local.json')
    . (Join-Path $root 'scripts\load-model-config.ps1') -ProjectRoot $fixture
    Assert-Equal $env:HF_HOME (Join-Path $fixture 'models\huggingface')
    Assert-Equal $env:SPEAKBRIDGE_LLAMA_SERVER (Join-Path $fixture 'runtime\llama-cuda\llama-server.exe')
    foreach ($name in $variables | Where-Object { $_ -notin @('SPEAKBRIDGE_LLAMA_DEVICE', 'TRANSFORMERS_CACHE', 'PYTORCH_TRANSFORMERS_CACHE', 'PYTORCH_PRETRAINED_BERT_CACHE', 'HUGGINGFACE_HUB_CACHE') }) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not $value.StartsWith($fixture + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Path outside fixture: $name=$value" }
    }
    Write-Host 'PASS: installation-relative model/cache paths and legacy override removal.'
} finally {
    foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    if (-not $fixture.StartsWith([IO.Path]::GetFullPath($temporaryRoot) + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup path.' }
    if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force }
}
