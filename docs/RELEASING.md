# Windows release process

## Preconditions

- Clean Git worktree on the release commit.
- Node.js 22.13+, Python 3.11, and the project `.venv` installed.
- Version in `package.json`, backend metadata, and `CHANGELOG.md` agree.
- `npm audit`, `npm run lint`, and `npm test` pass.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

The script builds the helper executable and creates a model-free ZIP plus SHA-256 checksum under `release/`.

## Publish

1. Tag the audited commit, for example `v0.1.0`.
2. Create a GitHub release from that tag.
3. Attach the ZIP and `SHA256SUMS.txt`.
4. Copy the matching changelog section into the release notes.
5. Test installation from the downloaded ZIP in a new directory or Windows VM.

## Code signing

Community builds are unsigned and may trigger Windows SmartScreen. A trusted release should sign every EXE and installer with an Authenticode certificate before checksums are generated. Never publish private signing keys or certificates in the repository or CI artifacts.
