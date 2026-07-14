# Changelog

## Unreleased

### Added

- Versioned UTF-8 JSON Lines protocol and a standalone ASR Worker diagnostic process.
- Main-process Worker client with request timeouts, structured remote errors, progress events,
  and safe child-process shutdown.

## 0.3.0-dev — 2026-07-13

### Added

- Split base, cloud, local, and development dependency sets.
- Shared library scanner and relative-path instrumental marker store.
- Runtime `doctor` command for ffmpeg, dependency, Provider, and model diagnostics.
- Long-audio chunking with merged LRC timestamps.
- Resumable, SHA-256-verified Whisper model downloads.
- Offline model downloads use the Echovault GitHub Release manifest directly.
- Medium model downloads verify both release parts, atomically assemble the full
  checkpoint, and remove temporary parts after success.
- The Windows directory build includes the CPU Whisper runtime for offline recognition.
- Streamed LocalSend uploads and browser downloads.
- Pytest regression suite, Windows PyInstaller build, and GitHub Actions CI.

### Changed

- Chinese transcription output is normalized to Simplified Chinese for `zh`,
  `zh-TW`, `Chinese`, and other common Chinese language identifiers.
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

- The packaged Windows application includes Torch/Whisper CPU support; CUDA remains a
  separate source-environment setup.
- Medium assembly temporarily requires about 6 GB of free disk space.
- The Windows directory bundle includes ffmpeg and is therefore relatively large.
