# Roadmap

This roadmap is directional. Contributions should prioritize measurable accuracy, privacy, and predictable latency over adding untested model dropdowns.

## 0.2 — Reproducible quality

- Add redacted Vietnamese/English/Chinese audio fixtures with explicit consent and compatible licensing.
- Publish ASR word-error-rate, translation quality, latency, VRAM, and false-trigger benchmarks.
- Add unit tests for VAD segmentation, hallucination guards, language routing, and glossary behavior.
- Add structured diagnostic export with transcript redaction enabled by default.

## 0.3 — Broader Windows testing

- Validate multiple NVIDIA GPU and microphone configurations.
- Test Discord, Zoom, Meet, Word, Chrome, and common Electron applications.
- Add accessible overlay controls, sound toggle, and position persistence.
- Document CPU-only and lower-VRAM limitations from measured results.

## 1.0 — Stable release

- Signed Windows installer and reproducible release provenance.
- Versioned configuration migration and uninstall flow.
- Stable local API contract and contributor documentation.
- Published privacy threat model and third-party license review.

## Non-goals for now

- Cloud processing by default.
- Claiming support for a language without end-to-end tests.
- Bundling multi-gigabyte model weights in Git or GitHub releases.
- Safety-critical interpretation guarantees.
