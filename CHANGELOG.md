# Changelog

## Unreleased

### Fixed

- Packaged offline translation now keeps Argos diagnostic logging out of the structured
  CLI capture file, so AI/MCP callers always receive parseable JSON.
- Xunfei Speed Transcription now uses the documented `zh_cn` language modes, accepts
  JSON-string task results, rejects unsupported languages before upload, and explains
  service-license error 11200 with the required console action.
- Windows CI test jobs now install ffmpeg/ffprobe before running the audio integration test.
- The PyInstaller directory build now bundles `psutil`, so packaged local-ASR resource
  monitoring can report CPU and memory usage instead of placeholders.
- Windowed builds now return captured CLI output to the in-app AI command bridge without
  showing a console window or exposing API keys.

### Added

- A fourth right-side Online Matching tab backed by LRCLIB, with metadata-assisted search,
  ranked candidates, online preview, local/reference similarity, and synchronized-LRC download.
- AI lyric calibration against a public reference while preserving every local timestamp
  prefix and media file, with atomic writes, incremental backups, CLI/MCP commands, and a
  detailed matching and recovery guide.
- Timestamp-preserving single/batch LRC translation from the Details preview, using the
  selected AI endpoint or downloadable Argos offline language packages; translated LRCs
  use language suffixes and never overwrite the source.
- `lyrics translate` CLI/MCP write command and a detailed translation guide covering
  privacy, local model download, output naming, batch behavior, and recovery.
- A fifth Settings entry for local AI, with online/local switching, Ollama and LM Studio
  presets, an optional local bearer token, and a shared OpenAI-compatible chat interface.
- Detailed online/local AI request schema, configuration, environment variable, security,
  and troubleshooting documentation.
- MCP stdio/Streamable HTTP server backed by the existing CLI whitelist, with read-only
  defaults and two-step authorization for mutating commands.
- Detailed MCP client configuration, tool schema, security, and validation guide.
- Versioned UTF-8 JSON Lines protocol and a standalone ASR Worker diagnostic process.
- Main-process Worker client with request timeouts, structured remote errors, progress events,
  and safe child-process shutdown.
- Cross-vendor Windows display-adapter detection and CUDA/WinML/CPU runtime recommendation.
- Signed-manifest runtime manager with resumable downloads, SHA-256 verification, safe ZIP
  extraction, atomic activation, and project-scoped cleanup.
- External CPU/CUDA Worker Whisper transcription with actual-device reporting and CUDA OOM errors.
- One-click local runtime setup in Settings: cross-vendor detection, signed Release manifest
  retrieval, staged Worker self-test, activation, cancellation, and CPU selection.

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
