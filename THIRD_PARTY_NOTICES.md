# Third-party model and library notices

SpeakBridge does not redistribute model weights. Users download and use each
model under its own license. The official Hy-MT2 GGUF repository and expected
Q6_K filename are recorded below so release installers do not rely on an
untraceable third-party conversion.

- [Hy-MT2 7B GGUF](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) — Apache License 2.0.
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — Apache License 2.0.
- [Silero VAD](https://github.com/snakers4/silero-vad) — MIT License.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — MIT License.
- [Whisper](https://github.com/openai/whisper) — MIT License.

VB-CABLE is separate software from VB-Audio. It is not included in this
repository and remains subject to the terms published by VB-Audio.

The Windows hotkey executable includes a Python runtime and the packages
listed in `desktop/requirements.txt`. Redistributable license texts for the
bundled runtime and direct helper dependencies are stored in `licenses/`.
Notably, pystray is LGPL-3.0; SpeakBridge publishes the complete helper source
in `desktop/hotkey_helper.py` and does not restrict reverse engineering needed
to debug or replace that library. PyInstaller's bootloader is distributed
under its GPL license with the project's special exception.

The web application uses React and related npm packages under their respective
licenses. The authoritative dependency versions and integrity hashes are in
`package-lock.json`; `npm audit` is run before a release.
