param([Parameter(Mandatory = $true)][string]$ProjectRoot)

$ConfigPath = Join-Path $ProjectRoot "config\models.local.json"
$ProjectCache = Join-Path $ProjectRoot ".model-cache"
$Values = [ordered]@{
    hf_home = Join-Path $ProjectRoot "models\huggingface"
    torch_home = Join-Path $ProjectCache "torch"
    pip_cache = Join-Path $ProjectCache "pip"
    npm_cache = Join-Path $ProjectCache "npm"
    runtime_temp = Join-Path $ProjectCache "temp"
    hy_mt2_model = Join-Path $ProjectRoot "models\HY-MT2-7B-Q6_K.gguf"
    llama_server = Join-Path $ProjectRoot "runtime\llama-cuda\llama-server.exe"
    llama_device = "CUDA0"
}

if (Test-Path -LiteralPath $ConfigPath) {
    $LocalValues = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    foreach ($Name in @($Values.Keys)) {
        if ($LocalValues.$Name) {
            $Candidate = [string]$LocalValues.$Name
            $Values[$Name] = if ($Name -eq "llama_device") {
                $Candidate
            } elseif ([System.IO.Path]::IsPathRooted($Candidate)) {
                [System.IO.Path]::GetFullPath($Candidate)
            } else {
                [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Candidate))
            }
        }
    }
}

foreach ($Directory in @($Values.hf_home, $Values.torch_home, $Values.pip_cache, $Values.npm_cache, $Values.runtime_temp)) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
}

$env:HF_HOME = $Values.hf_home
$env:HF_HUB_CACHE = Join-Path $Values.hf_home "hub"
$env:HF_XET_CACHE = Join-Path $Values.hf_home "xet"
$env:HF_MODULES_CACHE = Join-Path $Values.hf_home "modules"
# Inherited legacy overrides must not redirect downloads to the user profile.
foreach ($Legacy in @('TRANSFORMERS_CACHE', 'PYTORCH_TRANSFORMERS_CACHE', 'PYTORCH_PRETRAINED_BERT_CACHE', 'HUGGINGFACE_HUB_CACHE')) {
    Remove-Item -LiteralPath "Env:$Legacy" -ErrorAction SilentlyContinue
}
$env:TORCH_HOME = $Values.torch_home
$env:XDG_CACHE_HOME = $ProjectCache
$env:UV_CACHE_DIR = Join-Path $ProjectCache 'uv'
$env:NUMBA_CACHE_DIR = Join-Path $ProjectCache 'numba'
$env:PIP_CACHE_DIR = $Values.pip_cache
$env:npm_config_cache = $Values.npm_cache
$env:TEMP = $Values.runtime_temp
$env:TMP = $Values.runtime_temp
$env:SPEAKBRIDGE_HY_MODEL = $Values.hy_mt2_model
$env:SPEAKBRIDGE_LLAMA_SERVER = $Values.llama_server
$env:SPEAKBRIDGE_LLAMA_DEVICE = $Values.llama_device
$script:SpeakBridgeModelConfig = $Values
