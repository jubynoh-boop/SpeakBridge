# SpeakBridge

Local, two-way speech translation for Windows meetings, calls, media, and push-to-talk voice typing.

> **Alpha software:** SpeakBridge works end-to-end on the maintainer's Windows 11 / RTX 4070 Ti SUPER system, but it has not yet been validated across a broad hardware matrix. Do not rely on it for emergency, legal, medical, or other safety-critical interpretation.

[Tiếng Việt](docs/README.vi.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)

## What it does

- **You speak:** microphone → transcription → translation → optional English/Chinese TTS → VB-CABLE → Discord, Zoom, or Meet.
- **They speak:** Windows system audio → transcription → translation → local subtitles, without reading the translation aloud.
- **Voice typing:** hold a configurable global hotkey, speak, release, and paste the transcript or translation into the focused Windows app.
- **Private by default:** meeting audio and text stay on the PC. Model downloads are the only expected cloud traffic during setup.

```text
Microphone / WASAPI loopback
        ↓
Silero VAD → Faster-Whisper → Hy-MT2 7B → subtitles
                                      └→ Kokoro TTS → VB-CABLE
```

## Supported and tested

| Capability | Tested languages | Notes |
|---|---|---|
| Speech recognition | Vietnamese, English, Chinese | Whisper supports more languages, but they are not exposed until tested end-to-end. |
| Translation | Vietnamese, English, Chinese | Powered by Hy-MT2 7B. |
| Speech output | English, Chinese | The remote-party subtitle stream is silent by design. |
| Voice typing | Vietnamese, English, Chinese | Can transcribe or translate before pasting. |

## Requirements

- Windows 11 x64
- NVIDIA GPU with recent drivers; 16 GB VRAM is the tested target
- Python 3.11
- Node.js 22.13 or newer
- [VB-CABLE](https://vb-audio.com/Cable/) for virtual microphone routing
- About 20 GB of free space for the default models and caches
- Internet access for first-time setup only

The default translator is the official `tencent/Hy-MT2-7B-GGUF` Q6_K file (~6.16 GB). Model weights are downloaded during setup and are never committed to this repository or bundled in releases.

## Quick start

1. Download and extract the Windows release ZIP to a folder with enough free space.
2. Double-click `SPEAKBRIDGE.bat` and choose **1** for first-time setup. The installer creates local caches inside the extracted folder unless `config/models.local.json` points elsewhere.
3. From the same menu, choose **2** to download and launch the official VB-CABLE driver installer when virtual microphone output is required. Approve the Administrator prompt and reboot Windows afterward. VB-CABLE remains a separate Donationware product from VB-Audio and is not bundled with SpeakBridge.
4. Run `SPEAKBRIDGE.bat` again and choose **3** to start.
5. Open `http://127.0.0.1:3000` if the browser does not open automatically.

For subsequent sessions, use the same `SPEAKBRIDGE.bat` menu to start or stop all local processes. Developer build options are shown only in a Git working copy; they are hidden from the end-user release menu.

### Meeting audio routing

1. SpeakBridge microphone: your physical USB/headset microphone.
2. SpeakBridge translated output: `CABLE Input (VB-Audio Virtual Cable)`.
3. Discord/Zoom/Meet microphone: `CABLE Output (VB-Audio Virtual Cable)`.
4. Discord/Zoom/Meet speaker: your real headphones.
5. SpeakBridge remote-party capture: the same real headphones from step 4.

Do not select `CABLE In 16ch` as the meeting speaker for this one-cable setup.

## Models and local storage

Copy `config/models.example.json` to `config/models.local.json` only when you want custom locations. Relative paths keep all caches in the SpeakBridge directory. Local configuration, model weights, logs, virtual environments, Node dependencies, and build output are ignored by Git.

```json
{
  "hf_home": ".model-cache/huggingface",
  "torch_home": ".model-cache/torch",
  "pip_cache": ".model-cache/pip",
  "npm_cache": ".model-cache/npm",
  "runtime_temp": ".model-cache/temp",
  "hy_mt2_model": "models/HY-MT2-7B-Q6_K.gguf"
}
```

Menu option **5** downloads Hy-MT2, Faster-Whisper Turbo, Kokoro, and the tested voices. `QUALITY` mode downloads/loads Whisper large-v3 separately when first used.

## Voice typing

Launch `desktop/dist/SpeakBridgeHotkey.exe`, then place the caret in Discord, Chrome, Word, or another text field. The helper starts the installed local engine in the background when necessary; the browser page does not need to remain open. Wait for **READY**, hold the configured hotkey (default `Ctrl+Alt+Space`), speak, then release it. The generated text remains on the clipboard as a manual `Ctrl+V` fallback.

SpeakBridge does not press Enter automatically. Some elevated games and protected applications reject synthetic paste events; run applications at the same privilege level and follow their rules.

## Development

```powershell
npm ci
npm run lint
npm test

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Build the Windows hotkey helper or a clean release ZIP with developer options **6** and **7** in `SPEAKBRIDGE.bat`, or run the PowerShell build script directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

See [docs/RELEASING.md](docs/RELEASING.md) for signing and release instructions.

## Privacy and security

Services bind to loopback interfaces and process meeting content locally. Logs may contain transcripts and should not be attached to public issues without review. Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## Limitations

- Translation is clause-based streaming, not simultaneous token-level speech translation.
- Accuracy depends heavily on microphone level, room noise, accent, and meeting vocabulary.
- The first request after launch is slower while models load into memory.
- The Windows executable is unsigned unless the release maintainer signs it; Windows SmartScreen may warn on community builds.
- The release ZIP does not include Python, Node.js, VB-CABLE, llama.cpp, CUDA libraries, or model weights.

## License

SpeakBridge source code is licensed under the [Apache License 2.0](LICENSE). Models and third-party software remain under their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
