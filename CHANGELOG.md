# Changelog

All notable changes are documented here. This project follows semantic versioning after the first stable release.

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
