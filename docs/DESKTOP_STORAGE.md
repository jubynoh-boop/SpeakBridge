# Desktop storage layout

Model configuration uses paths relative to the installation directory, resolved by `scripts/load-model-config.ps1`, not by the terminal's current directory.

```text
SpeakBridge/
  SPEAKBRIDGE.bat
  config/
    models.example.json       # distributable defaults
    models.local.json         # private machine configuration; never publish
    speech.example.json
    speech.local.json         # optional Vietnamese engine selection
  models/
    HY-MT2-7B-Q6_K.gguf        # translator
    huggingface/hub/           # Whisper FAST/QUALITY and Kokoro + voice packs
    vieneu-v3-turbo/           # optional Vietnamese ONNX TTS and codec
  .model-cache/
    rapidocr/                 # OCR models, including Korean recognizer
    supertonic3/              # Japanese/Korean and fallback Vietnamese TTS
    torch/ uv/ pip/ npm/       # rebuildable caches
    temp/ numba/ vieneu/       # temporary/runtime artifacts
  runtime/
    llama-cuda/               # local translator executable and CUDA DLLs
    vieneu/.venv/             # isolated optional CPU speech environment
  .venv/                      # main Python dependencies (includes Silero VAD)
  node_modules/               # current web frontend dependencies
  .run/                       # private local logs, process identities, diagnostics
```

The layout does not require `realtime-Translator`, a separate VieNeu checkout, ComfyUI, or a shared `AI-Cache` directory. Custom absolute paths remain supported, but create dependencies outside this installation.

## Verification after a path change

1. Copy files first, retaining the source. Verify SHA-256 of source and copy. Hugging Face snapshot files must not link to storage outside this installation.
2. Back up `config/models.local.json`, then use the relative defaults in `models.example.json`. Preserve any deliberately customized device selection.
3. Stop this installation with `stop.ps1`, then start it with `start.ps1`. A running llama-server retains its original model path until restarted.
4. Check `/models/status`: every installed asset should resolve under this installation. Check offline FAST and QUALITY model loads, translation, OCR, and voice output. The local migration report in `.run` is private and is not a release artifact.

## Packaging boundaries

The public bootstrap ZIP deliberately excludes model weights, caches, local settings, credentials, meeting logs and documents. Users download models during setup. Do not zip the working directory as a public release.

Python virtual environments contain interpreter references and are not portable simply because their model paths are relative. This preparation is not a standalone `Setup.exe`: a future desktop distribution must bundle or install supported Python/Node runtimes, handle prerequisites, licenses and updates, and pass clean-machine installation tests. VB-CABLE remains a separate driver installation with administrator consent. API keys protected by Windows DPAPI must be entered again under a different Windows account.

Keep older shared sources until other applications no longer need them. No source-model cleanup is required for SpeakBridge to work independently.
