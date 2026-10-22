# Changelog

All notable changes are documented here. This project follows semantic versioning after the first stable release.

## Unreleased

### Fixed

- The 1.08x Supertonic rollback still repeated words in the reported sentence. Added an opt-in VieNeu v3 Turbo 3.8.3 CPU worker, isolated from the main Python environment and cached on the app drive.
- Preserve saved M1/F1 IDs, expose actual Hải Đăng/Trúc Ly names, validate local assets, and retain all other language engines.
- Add repeated-fixture benchmarks and worker/manifest tests. Offline startup never downloads replacement voices automatically.

- Reject token-truncated translations instead of speaking an incomplete prefix; split long text while preserving all source words.
- Bound Vietnamese speech chunks without aggressively shortening phrase context; use 8 Supertonic steps, 1.08x Vietnamese speed, and 120 ms inter-chunk pauses. Keep quiet syllables intact (no breath gate). The 1.12x experiment was reverted after phrase repetition regression.
- Log selected-read translation/generation/playback durations separately without logging the selected text.
- Include the CUDA installer and all Python regression tests in the Windows bootstrap release; run Python tests in the release gate.
- Use one documented launcher (`SPEAKBRIDGE.bat`); validate process paths and creation times before shutdown, and reject occupied ports belonging to another installation.

### Security

- Protect advisor API keys using current-user Windows DPAPI, migrate old local plaintext settings, and allow replacing keys copied from another Windows account.
- Ignore incremental TypeScript output, downloader logs, and temporary configuration writes.

## [0.2.0] - 2026-08-26

### Added

- Grounded AI reply-advisor panel between the incoming and outgoing transcript streams, with configurable silence/sentence triggers, soft-deal mode, source citations, and strict document scope.
- Local document indexing for DOCX, text DOC, TXT, MD, CSV, JSON, and HTML meeting/service knowledge.
- Provider settings for OpenAI API, Anthropic Claude, DeepSeek, 9Router, and custom OpenAI-compatible endpoints; secrets remain in ignored machine-local configuration.
- Windows-wide typed-text translation: `F8` translates selected text, or the entire focused chat input, and replaces it without submitting the message.
- Local on-screen text translation for videos, livestreams, games, and documents.
- Browser screen/window/tab capture with explicit drag-to-select or full-image modes.
- User-selectable CPU OCR (ONNX Runtime) or GPU OCR (PyTorch CUDA), with automatic CPU fallback.
- PP-OCRv6 Chinese/English text recognition with translated text overlaid on the original OCR boxes, unchanged-frame deduplication, history, and `.doc` export.
- Overlay text now stays on one line and auto-fits inside the exact OCR box; the translated image preview also supports fullscreen viewing without coordinate drift.
- Windows desktop region translation: press `Ctrl+Alt+T`, drag over any application, and receive a local, always-on-top, click-through translation overlay at the original OCR coordinates.
- Desktop selection now uses a frozen screenshot with an explicit crop rectangle and an input grab, fixing cases where the translucent selector appeared to do nothing.
- Desktop overlays now support an adjustable 8–48 px font, controlled expansion beyond the OCR box, cursor-monitor selection on multi-monitor systems, global `Esc` dismissal, and an optional status bar.
- Desktop regions can now run continuously for video subtitles, keep the overlay until explicitly stopped, skip repeat translation when OCR text is unchanged, and use a configurable exit shortcut (`Esc` by default).
- Continuous desktop overlays are excluded from Windows screenshots to eliminate capture blinking, reuse their text labels in-place, and expose configurable 0.25–10 second refresh delay plus 20–100% opacity.

### Changed

- Global hotkey callbacks no longer block Ctrl/Shift while opening or closing the microphone.
- Release setup now downloads the OCR models during model preparation.

## [0.1.0] - 2026-08-19

### Added

- Two-way local meeting translation for Vietnamese, English, and Chinese.
- WASAPI loopback subtitles for remote-party and media audio.
- English and Chinese Kokoro speech output through VB-CABLE.
- Global push-to-talk voice typing with translation, clipboard fallback, status overlay, and soft chimes.
- Hotkey helper automatically starts the local engine in the background when needed.
- Meeting context, glossary/hotwords, transcript history export, and bilingual UI.
- Offline runtime after first-time model setup.

### Security and reliability

- Localhost-only frontend/backend launch defaults.
- Noise, low-confidence, repetition, and hallucination guards.
- Machine-local paths, model weights, logs, caches, and build output excluded from source control and releases.
- Public defaults and documentation use generic glossary examples rather than private project names.
