# SpeakBridge

Local, two-way speech translation for Windows meetings, calls, media, and push-to-talk voice typing.

> **Alpha software:** SpeakBridge works end-to-end on the maintainer's Windows 11 / RTX 4070 Ti SUPER system, but it has not yet been validated across a broad hardware matrix. Do not rely on it for emergency, legal, medical, or other safety-critical interpretation.

[Tiếng Việt](docs/README.vi.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)

## What it does

- **You speak:** microphone → transcription → translation → optional Vietnamese/English/Chinese/Japanese/Korean TTS → VB-CABLE → Discord, Zoom, or Meet.
- **They speak:** Windows system audio → transcription → translation → local subtitles, without reading the translation aloud.
- **Voice typing:** hold a configurable global hotkey, speak, release, and paste the transcript or translation into the focused Windows app.
- **Typed-text translation:** press a configurable global hotkey to translate selected Vietnamese text—or the entire focused chat input—into English and replace it in place.
- **Read selected text aloud:** highlight copyable text with the mouse, then press `Ctrl+Alt+R` to hear it or its translation through the Windows default speaker. Requires the Windows hotkey helper; it does not change screen OCR translation.
- **Private by default:** meeting audio and text stay on the PC. The optional AI advisor sends only the selected meeting context and retrieved document excerpts to the API provider you explicitly configure.

```text
Microphone / WASAPI loopback
        ↓
Silero VAD → Faster-Whisper → Hy-MT2 7B → subtitles
                                      └→ Kokoro / Supertonic TTS → VB-CABLE
```

## Supported and tested

| Capability | Tested languages | Notes |
|---|---|---|
| Speech recognition | Vietnamese, English, Chinese; Japanese/Korean experimental | Whisper is multilingual; select the known input language for more reliable results. |
| Translation | Vietnamese, English, Chinese; Japanese/Korean experimental | Powered by Hy-MT2 7B. Live audio quality varies by speaker and noise. |
| Speech output | English/Chinese via Kokoro; Vietnamese/Japanese/Korean via Supertonic 3 | 02A remains silent by design. Supertonic runs on CPU and stays in `.model-cache` on the app drive. |
| Screen OCR | Chinese/English/Japanese via PP-OCRv6; Korean via PP-OCRv5 | Korean OCR falls back to CPU; set the source language explicitly. |
| Voice typing | Vietnamese, English, Chinese; Japanese/Korean experimental | Can transcribe or translate before pasting. |

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
2. Double-click `SPEAKBRIDGE.bat` and choose **1 — First-time setup**. The installer creates local caches inside the extracted folder unless `config/models.local.json` points elsewhere.
3. Install VB-CABLE separately if virtual microphone output is required.
4. In the same launcher, choose **3 — Start SpeakBridge**.
5. Open `http://127.0.0.1:3000` if the browser does not open automatically.

For subsequent sessions, open `SPEAKBRIDGE.bat` and choose **3**. Choose **4** to stop this installation's local processes. Items **6/7** are developer build tools, not alternate app launchers.

### Meeting audio routing

1. SpeakBridge microphone: your physical USB/headset microphone.
2. SpeakBridge translated output: `CABLE Input (VB-Audio Virtual Cable)`.
3. Discord/Zoom/Meet microphone: `CABLE Output (VB-Audio Virtual Cable)`.
4. Discord/Zoom/Meet speaker: your real headphones.
5. SpeakBridge remote-party capture: the same real headphones from step 4.

Do not select `CABLE In 16ch` as the meeting speaker for this one-cable setup.

Panel 02B's **Test voice** button synthesizes a short sample through the selected output without using the microphone or translator. Choose real headphones to hear it yourself; `CABLE Input` sends it to the virtual microphone instead. Available voice packs are checked locally; missing packs are disabled. English uses Adam, Michael, George, Lewis or Heart; Chinese uses Yunxi; Vietnamese, Japanese and Korean offer M1/F1.

## Models and local storage

Copy `config/models.example.json` to `config/models.local.json` only when you want custom locations. Relative paths keep all caches in the SpeakBridge directory. Local configuration, model weights, logs, virtual environments, Node dependencies, and build output are ignored by Git.

```json
{
  "hf_home": "models/huggingface",
  "torch_home": ".model-cache/torch",
  "pip_cache": ".model-cache/pip",
  "npm_cache": ".model-cache/npm",
  "runtime_temp": ".model-cache/temp",
  "hy_mt2_model": "models/HY-MT2-7B-Q6_K.gguf"
}
```

Choose **5 — Prepare models** in `SPEAKBRIDGE.bat` to download Hy-MT2, Faster-Whisper Turbo, Kokoro, Supertonic 3, and the Japanese/Korean OCR models into the app drive or the configured cache drive. `QUALITY` mode downloads/loads Whisper large-v3 separately when first used.

The default layout is self-contained: Hy-MT2, Whisper and Kokoro live in `models/`; OCR and Supertonic stay in `.model-cache/`. No sibling repository is required. See [Desktop storage layout](docs/DESKTOP_STORAGE.md) for relocation and packaging limitations. Consolidating models does not make the existing Python/Node virtual environments portable or create a desktop installer.

Vietnamese/Japanese/Korean speech runs locally with Supertonic on CPU. Long passages are split into bounded chunks, with 8 synthesis steps and 120 ms inserted between chunks. Vietnamese keeps up to 450 characters of context and uses 1.08x synthesis speed; the previous 1.12x setting regressed phrase repetition tests. Reading time is separate from generation time; `/text/read` reports both. Higher synthesis quality costs more generation time. A translation that reaches its token limit is rejected rather than silently read as complete. Model pronunciation can still be imperfect, especially for names and mixed-language text. No breath/noise gate is applied to speech, to avoid cutting quiet syllables.

For better Vietnamese speech, the optional **VieNeu v3 Turbo 3.8.3** engine runs in `runtime/vieneu/.venv` on CPU, independent of the main Python environment. Run `powershell -ExecutionPolicy Bypass -File scripts/prepare-vieneu.ps1`, then opt in with `config/speech.local.json` containing `{"vietnamese_engine":"vieneu"}` and restart the backend. Downloads remain in `models/vieneu-v3-turbo` on the app drive; startup is offline. Existing Vietnamese IDs M1/F1 map to Hải Đăng/Trúc Ly and the voice dropdown shows their real names. English/Chinese/Japanese/Korean engines are unchanged. Set the engine back to `supertonic` to roll back. This is not a promise of error-free pronunciation: repeated fixed-fixture tests and listening to the WAVs are still necessary. CPU generation was about 1.2 seconds for the reported Vietnamese sentence on the test PC after model load; the first call also loads sessions.

Advisor API keys are protected with Windows current-user DPAPI. Local configuration and backups remain private: do not commit or distribute them. A protected key copied to a different Windows account must be entered again.

## Voice typing

Launch `desktop/dist/SpeakBridgeHotkey.exe`, then place the caret in Discord, Chrome, Word, or another text field. The helper starts the installed local engine in the background when necessary; the browser page does not need to remain open. Wait for **READY**, hold the configured hotkey (default `Ctrl+Alt+Space`), speak, then release it. The generated text remains on the clipboard as a manual `Ctrl+V` fallback.

To translate text you have already typed, select only the part you want to translate or leave the caret in the input to use its entire contents, then press `F8`. SpeakBridge replaces the selected/input text with the translated result without pressing Enter.

To read text aloud, highlight copyable text in a browser or app first, then press `Ctrl+Alt+R` and release the keys. The Settings panel lets you choose **Read original text** or **Translate, then read**, with automatic source-script detection or an explicit language. No screenshot is taken and no OCR box appears. If nothing is selected or the app blocks copying, SpeakBridge reports an error without selecting the entire page. This is separate from the live screen OCR overlay. Choose the read-aloud playback device in Settings; it is independent of the VB-CABLE output used by panel 02B.

SpeakBridge does not press Enter automatically. Some elevated games and protected applications reject synthetic paste events; run applications at the same privilege level and follow their rules.

Use **Settings → Check helper / shortcuts** to see whether the helper is running and Windows has accepted each shortcut. An occupied shortcut is reported explicitly; choose another combination and save. For example, `Ctrl+Shift+F9` can replace an occupied read-aloud shortcut. The helper reloads saved settings within two seconds. A running browser page alone does not mean the Windows helper is active.

**Settings → Show helper progress on screen** saves immediately and shows whether the helper confirmed the change. Hiding the status bar does not disable shortcuts, translation, the tray icon or screen OCR overlays.

In **Settings → Read highlighted text aloud**, select a voice and click **Save hotkey settings**. Voice preferences are saved per language, separately from panel 02B. Original mode uses the source language's voice; translated mode uses the target language's voice. In Auto original mode, configure each language's voice using the extra language selector. **Test selected voice** plays through the read-aloud speaker without capturing text.

For read-aloud, choose **Settings → Read highlighted text aloud → Speaker/headphones**, click **Test sound**, then save. This device is independent of panel 02B's virtual microphone output. Choose your physical headphones to hear the selected text yourself; a disconnected device reports an error instead of silently routing speech elsewhere.

## Optional AI meeting advisor

The center panel can suggest grounded replies after the remote speaker finishes a sentence or remains silent for a configurable delay. Upload service knowledge or previous meeting logs, enable **Stay within uploaded sources**, and optionally enable the soft-deal mode. Document retrieval runs locally; only the relevant excerpts, recent transcript context, and current utterance are sent to the configured provider.

Supported providers are OpenAI API, Anthropic Claude, DeepSeek, **9Router**, and a custom OpenAI-compatible endpoint. The 9Router default is `http://127.0.0.1:20128/v1` with the `auto` alias. API keys are stored only in ignored `config/advisor.local.json`; they are never returned to the browser or committed. OpenAI API billing is separate from ChatGPT/Codex subscriptions.

Uploaded advisor documents are stored under ignored `.advisor-data/`. Supported formats are DOCX, text-based DOC, TXT, MD, CSV, JSON, and HTML. Legacy binary `.doc` files should be saved as `.docx` first.

## Development

```powershell
npm ci
npm run lint
npm test

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Build the Windows hotkey helper with `powershell -ExecutionPolicy Bypass -File desktop/build-hotkey.ps1`. Build a clean release ZIP with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

See [docs/RELEASING.md](docs/RELEASING.md) for signing and release instructions.

## Privacy and security

Services bind to loopback interfaces and process meeting content locally unless the optional AI advisor is enabled. Advisor requests go to the provider/base URL selected by the user. Logs and uploaded documents may contain sensitive material and should not be attached to public issues without review. Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## Limitations

- Translation is clause-based streaming, not simultaneous token-level speech translation.
- Accuracy depends heavily on microphone level, room noise, accent, and meeting vocabulary.
- The first request after launch is slower while models load into memory.
- The Windows executable is unsigned unless the release maintainer signs it; Windows SmartScreen may warn on community builds.
- The release ZIP does not include Python, Node.js, VB-CABLE, llama.cpp, CUDA libraries, or model weights.

## License

SpeakBridge source code is licensed under the [Apache License 2.0](LICENSE). Models and third-party software remain under their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
