param([Parameter(Mandatory = $true)][string]$ProjectRoot)

$ErrorActionPreference = "Stop"
$Version = "b10981"
$CudaVersion = "13.4"
$RuntimeDir = Join-Path $ProjectRoot "runtime\llama-cuda"
$CacheDir = Join-Path $ProjectRoot ".model-cache\temp\llama-cuda"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ServerExe = Join-Path $RuntimeDir "llama-server.exe"

if ((Test-Path -LiteralPath $ServerExe) -and ((& $ServerExe --list-devices 2>&1 | Out-String) -match "CUDA0")) {
    Write-Host "llama.cpp CUDA is already ready: $ServerExe" -ForegroundColor Green
    return
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python environment is missing: $PythonExe"
}

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$Packages = @(
    @{
        Name = "llama-$Version-bin-win-cuda-$CudaVersion-x64.zip"
        Url = "https://github.com/ggml-org/llama.cpp/releases/download/$Version/llama-$Version-bin-win-cuda-$CudaVersion-x64.zip"
    },
    @{
        Name = "cudart-llama-bin-win-cuda-$CudaVersion-x64.zip"
        Url = "https://github.com/ggml-org/llama.cpp/releases/download/$Version/cudart-llama-bin-win-cuda-$CudaVersion-x64.zip"
    }
)

foreach ($Package in $Packages) {
    $Destination = Join-Path $CacheDir $Package.Name
    if (-not (Test-Path -LiteralPath $Destination)) {
        Write-Host "Downloading $($Package.Name) to $CacheDir..." -ForegroundColor Cyan
        $DownloadCode = @'
import pathlib
import sys
from pip._vendor import requests

url, destination = sys.argv[1], pathlib.Path(sys.argv[2])
partial = destination.with_suffix(destination.suffix + ".part")
with requests.get(url, stream=True, timeout=300) as response:
    response.raise_for_status()
    with partial.open("wb") as output:
        for chunk in response.iter_content(1024 * 1024):
            if chunk:
                output.write(chunk)
partial.replace(destination)
'@
        & $PythonExe -c $DownloadCode $Package.Url $Destination
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $($Package.Name)" }
    }
}

$StagingDir = Join-Path $CacheDir "extract-$Version"
if (Test-Path -LiteralPath $StagingDir) {
    Remove-Item -LiteralPath $StagingDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
foreach ($Package in $Packages) {
    Expand-Archive -LiteralPath (Join-Path $CacheDir $Package.Name) -DestinationPath $StagingDir -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $StagingDir "llama-server.exe"))) {
    throw "The official llama.cpp archive did not contain llama-server.exe"
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Copy-Item -Path (Join-Path $StagingDir "*") -Destination $RuntimeDir -Recurse -Force
Remove-Item -LiteralPath $StagingDir -Recurse -Force

$Devices = & $ServerExe --list-devices 2>&1 | Out-String
if ($Devices -notmatch "CUDA0") {
    throw "llama.cpp was installed, but CUDA0 was not detected.`n$Devices"
}
Write-Host "llama.cpp CUDA installed in $RuntimeDir and detected CUDA0." -ForegroundColor Green
