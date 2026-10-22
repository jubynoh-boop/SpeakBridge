param(
    [string]$Version = "",
    [switch]$SkipChecks,
    [switch]$SkipHelperBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))
$Package = Get-Content -LiteralPath (Join-Path $ProjectRoot "package.json") -Raw | ConvertFrom-Json
if (-not $Version) { $Version = [string]$Package.version }
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid release version: $Version"
}

$ReleaseRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "release"))
$StageName = "SpeakBridge-$Version-windows-x64"
$Stage = [System.IO.Path]::GetFullPath((Join-Path $ReleaseRoot $StageName))
$ZipPath = Join-Path $ReleaseRoot "$StageName.zip"
if (-not $Stage.StartsWith($ReleaseRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe release staging path: $Stage"
}

Set-Location -LiteralPath $ProjectRoot
if (-not $SkipChecks) {
    & npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { throw "Lint failed." }
    & npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    & npm.cmd audit --audit-level=high
    if ($LASTEXITCODE -ne 0) { throw "npm audit failed." }
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Missing project .venv." }
    & $PythonExe -c "import ast,pathlib; files=list(pathlib.Path('backend').glob('*.py'))+list(pathlib.Path('desktop').glob('*.py')); [ast.parse(p.read_text(encoding='utf-8')) for p in files]; print(f'Python syntax OK: {len(files)} files')"
    if ($LASTEXITCODE -ne 0) { throw "Python syntax check failed." }
    & $PythonExe -m unittest discover -s tests -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed." }
    & (Join-Path $ProjectRoot 'tests\model-paths.test.ps1')
}

if (-not $SkipHelperBuild) {
    & (Join-Path $ProjectRoot "desktop\build-hotkey.ps1")
}
$HelperExe = Join-Path $ProjectRoot "desktop\dist\SpeakBridgeHotkey.exe"
if (-not (Test-Path -LiteralPath $HelperExe)) { throw "Missing built helper: $HelperExe" }

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

$Files = @(
    ".editorconfig", ".gitattributes", ".gitignore",
    "SPEAKBRIDGE.bat", "CHANGELOG.md", "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md", "LICENSE", "NOTICE",
    "README.md", "ROADMAP.md", "SECURITY.md",
    "THIRD_PARTY_NOTICES.md", "eslint.config.mjs",
    "install.ps1", "next-env.d.ts", "package-lock.json", "package.json",
    "prepare-models.ps1", "start.ps1", "stop.ps1", "tsconfig.json", "vite.config.ts",
    "app\globals.css", "app\layout.tsx", "app\page.tsx", "lib\hotkeys.ts", "lib\speech-player.ts",
    "backend\__init__.py", "backend\requirements.txt", "backend\server.py",
    "backend\system_audio.py", "backend\screen_ocr.py", "backend\warmup.py", "backend\model_inventory.py", "backend\advisor.py", "backend\tts_voices.py", "backend\text_segments.py", "backend\local_secrets.py", "backend\vietnamese_tts.py", "backend\vieneu_worker.py",
    "config\hotkey.example.json", "config\models.example.json", "config\advisor.example.json", "config\speech.example.json",
    "desktop\build-hotkey.ps1", "desktop\hotkey_helper.py", "desktop\requirements.txt", "desktop\windows_hotkeys.py", "desktop\speech_output.py",
    "docs\CODEX_FOR_OSS_APPLICATION.md", "docs\README.vi.md", "docs\RELEASING.md", "docs\DESKTOP_STORAGE.md",
    "scripts\build-release.ps1", "scripts\install-vb-cable.ps1", "scripts\install-llama-cuda.ps1", "scripts\load-model-config.ps1", "scripts\process-ownership.ps1", "scripts\benchmark-vietnamese-tts.py", "scripts\check-tts-coverage.py",
    "tests\rendered-html.test.mjs", "tests\test_screen_ocr.py", "tests\hotkeys.test.mjs", "tests\test_hotkey_settings.py", "tests\test_model_inventory.py", "tests\speech-player.test.mjs", "tests\test_tts_voices.py", "scripts\check-local-voices.py",
    "tests\test_advisor.py", "tests\test_screen_read.py", "tests\test_selected_text_hotkey.py", "tests\test_speech_output.py", "tests\test_windows_hotkeys.py", "tests\test_text_segments.py", "tests\test_translation_limits.py", "tests\test_vietnamese_tts.py", "tests\process-ownership.test.ps1",
    "scripts\prepare-vieneu.ps1", "scripts\prepare-vieneu.py", "scripts\benchmark-vieneu.py", "scripts\check-vietnamese-stutter.py", "tests\model-paths.test.ps1"
)

foreach ($Relative in $Files) {
    $Source = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path -LiteralPath $Source)) { throw "Release input missing: $Relative" }
    $Destination = Join-Path $Stage $Relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "licenses") -Destination (Join-Path $Stage "licenses") -Recurse -Force
$StagedHelper = Join-Path $Stage "desktop\dist\SpeakBridgeHotkey.exe"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StagedHelper) | Out-Null
Copy-Item -LiteralPath $HelperExe -Destination $StagedHelper -Force

$Manifest = [ordered]@{
    name = "SpeakBridge"
    version = $Version
    platform = "windows-x64"
    built_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    model_weights_included = $false
    hy_mt2 = [ordered]@{
        repository = "tencent/Hy-MT2-7B-GGUF"
        filename = "HY-MT2-7B-Q6_K.gguf"
        expected_sha256 = "88ef0aba59952a4cfe4be36cb5baf797dbb370bc60e9dcbd7297036021e52831"
    }
    helper_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $StagedHelper).Hash.ToLowerInvariant()
}
$Manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Stage "RELEASE-MANIFEST.json") -Encoding utf8

Compress-Archive -LiteralPath $Stage -DestinationPath $ZipPath -CompressionLevel Optimal
$ZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath).Hash.ToLowerInvariant()
"$ZipHash  $(Split-Path -Leaf $ZipPath)" | Set-Content -LiteralPath (Join-Path $ReleaseRoot "SHA256SUMS.txt") -Encoding ascii

Write-Host "Release created:" -ForegroundColor Green
Write-Host "  $ZipPath"
Write-Host "  SHA256 $ZipHash"
