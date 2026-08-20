# Contributing to SpeakBridge

Thanks for helping improve local, accessible speech translation.

## Before opening a pull request

1. Open or reference an issue for user-visible changes.
2. Keep audio, transcripts, model weights, caches, and machine-local configuration out of commits.
3. Run `npm ci`, `npm run lint`, and `npm test`.
4. Run `python -m compileall -q backend desktop` with Python 3.11.
5. Test Windows audio or hotkey changes on a non-admin account and document the devices used.

## Pull request expectations

- Explain the user problem and the behavior change.
- Include reproduction and verification steps.
- Add or update tests for behavior that can run without downloading models.
- Preserve local-only defaults; new network behavior must be opt-in and documented.
- Do not weaken ASR noise/hallucination guards merely to make a single clip pass.

By submitting a contribution, you agree that it is licensed under Apache-2.0.
