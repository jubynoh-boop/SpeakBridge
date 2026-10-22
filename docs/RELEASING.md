# Windows release process

## Preconditions

- Clean Git worktree on the release commit.
- Node.js 22.13+, Python 3.11, and the project `.venv` installed.
- Version in `package.json`, backend metadata, and `CHANGELOG.md` agree.
- `npm audit`, `npm run lint`, `npm test`, and `.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'` pass.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

The script builds the helper executable and creates a model-free ZIP plus SHA-256 checksum under `release/`.

The ZIP includes the CUDA runtime installer script and all release-gate tests. It deliberately excludes local API credentials, model weights, `.run`, downloaded knowledge documents, caches, and development dependencies. This is still a bootstrap ZIP, not a bundled desktop Setup.exe; test Python/Node prerequisites in a clean Windows environment before publication.

Model paths default to installation-relative locations; see [Desktop storage layout](DESKTOP_STORAGE.md). A maintainer's consolidated model directory is not a public release package, and virtual environments must be installed or bundled correctly rather than copied from the development PC.

## Publish

1. Tag the audited commit, for example `v0.1.0`.
2. Create a GitHub release from that tag.
3. Attach the ZIP and `SHA256SUMS.txt`.
4. Copy the matching changelog section into the release notes.
5. Test installation from the downloaded ZIP in a new directory or Windows VM.

## Code signing

Community builds are unsigned and may trigger Windows SmartScreen. A trusted release should sign every EXE and installer with an Authenticode certificate before checksums are generated. Never publish private signing keys or certificates in the repository or CI artifacts.
