# Changelog

## 0.3.0-dev — 2026-07-13

### Added

- Split base, cloud, local, and development dependency sets.
- Shared library scanner and relative-path instrumental marker store.
- Runtime `doctor` command for ffmpeg, dependency, Provider, and model diagnostics.
- Long-audio chunking with merged LRC timestamps.
- Resumable, SHA-256-verified Whisper model downloads.
- Streamed LocalSend uploads and browser downloads.
- Pytest regression suite, Windows PyInstaller build, and GitHub Actions CI.

### Changed

- API keys now persist in the user configuration and are redacted in CLI output.
- Configuration and LRC files are written atomically.
- Local Whisper explicitly loads models on CPU or CUDA and safely falls back to CPU.
- GUI and CLI now share song scanning and instrumental marker behavior.
- Sync comparisons detect same-time/different-size conflicts and support strict hashing.
- Destructive mirror operations show a separate deletion confirmation.

### Security

- HTTP downloads are confined to the configured music library.
- LocalSend filenames are escaped and upload sizes are validated.
- Model downloads use normal TLS certificate validation and content hashes.

### Known limitations

- The packaged Windows MVP is cloud-first and intentionally excludes Torch/Whisper.
- The standalone local model release source still requires real-device validation.
- The Windows directory bundle includes ffmpeg and is therefore relatively large.
