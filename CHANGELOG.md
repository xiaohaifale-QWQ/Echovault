# Changelog

## Unreleased

### Fixed

- Fixed the transcription stop button being clipped below the status bar. It now
  uses a dedicated 24 px compact style instead of inheriting the global 32 px
  minimum button height inside an 18 px maximum-height constraint.
- Fixed a Windows startup crash in the frameless main window. The application no
  longer interprets Qt native-event pointers through `ctypes`; safe Qt
  `startSystemResize()` edge handles preserve four-edge and four-corner resizing
  without triggering a `QtCore.pyd` access violation while the window is shown.

### Changed

- Replaced Audio Editing's shared waveform/effect-panel template with eleven
  task-specific workspaces. Clip editing now combines precise extract/delete,
  gain, speed, pitch, delay, and fades; denoise compares original and processed
  waveforms; equalization uses eight vertical bands; multitrack tools provide
  track lanes, mute, solo, per-track volume, master gain, and stereo-channel
  assembly. Split, volume, normalization, extraction, and tags also have distinct
  workflows instead of generic parameter forms.
- Rebuilt Audio Editing around a real waveform timeline instead of a tool catalog.
  FFmpeg now extracts filled min/max peaks from WAV, FLAC, MP3, video, and other
  supported media; the editor provides a time ruler, playhead, drag selection,
  precise start/end/duration controls, wheel and button zoom, scrolling, zoom to
  selection, and selection-aware processing. Duplicate trim/edit and transport
  controls were consolidated, while File Management, Recording, and More Features
  were removed from this workspace. Completed results no longer replace the source
  waveform.
- Added Fluent-inspired, interruptible shell motion: the navigation indicator now
  moves between task workspaces, workspace headings use an 83 ms reveal, and the AI
  drawer opens and closes over 167 ms. Heavy tables, cover grids, waveforms, and
  scrolling content remain unanimated to avoid unnecessary repainting.
- Replaced the mismatched dark Windows caption on the main window with an integrated
  light title bar inspired by Codex. Native move, edge resize, minimize, maximize,
  restore, double-click maximize, and close behavior remain available.
- Added the new product header with brand, global material/function search, Batch
  Tasks, Model Library, and Settings. The legacy menu bar remains available as
  shortcuts internally but no longer occupies visible space.
- Applied a unified warm-white, rounded visual system to buttons, inputs, tabs,
  tables, cards, menus, progress bars, and scrollbars. Primary actions now use the
  same blue hierarchy throughout the desktop application.
- Completed a full screenshot audit of all workspaces and primary dialogs. Removed
  duplicated Batch Tasks entries and decorative glyphs, prevented inactive material
  actions from looking enabled, and replaced native spin-box arrows with clean
  text-entry controls.
- Rebalanced each task page: the material table prioritizes cover and song name,
  lyric translation no longer duplicates the original lyric pane, Audio Editing
  uses scrollable tool and parameter rails, Vocal Separation preserves full controls
  through a scrollable layout, Batch Tasks uses three compact cards, and phone
  transfer toolbars no longer cover the result table.
- Localized Settings, Key Manager, and Help dialog action buttons and sized each
  settings category to its actual content instead of inheriting the largest page.
- Replaced the seven equal right-side tabs with four task-oriented workspaces:
  Materials, Lyrics & Tags, Audio Editing, and Export & Transfer. Existing detailed
  behaviors remain available inside the relevant workspace instead of competing at
  the same navigation level.
- Moved the AI assistant from a fixed left column to a right-side drawer. The drawer
  is absent during normal work and appears only after AI Mode is started.
- Rebuilt Audio Editing as a continuous three-column workspace: categorized tools on
  the left, persistent material/waveform/playback in the center, and the selected
  tool's parameters on the right. Switching tools no longer loses the current media
  context.
- Added a selected-material action card that directly routes users to lyric work,
  cover/tag work, or audio editing, plus a global Batch Tasks shortcut.

## 0.5.0 - 2026-07-17

### Added

- Added a right-side Audio Editor workspace with a tool-grid home screen and
  expandable parameter pages for extraction, trim/edit, recording, concatenation,
  mixing, fades, speed/pitch, FFT denoise, loudness normalization, splitting,
  equalization, gain, common tags, conversion, channel/sample-rate changes, and
  reverse audio. Processing uses the bundled FFmpeg and preserves the original.
- Audio Editor pages can preview input/output files, open their output folder, and
  automatically register phone-session results in Pending Return for review and
  sending back to the source phone.
- Online Matching now searches MusicBrainz and Cover Art Archive for album artwork,
  previews selectable candidates, accepts local JPEG/PNG covers, and embeds the chosen
  image into common audio tags. The song list displays embedded covers as thumbnails.
- Processing artifacts from phone-transfer tasks are staged in a dedicated Pending
  Return folder. Same-volume files use NTFS hard links when possible, avoiding a
  second large WAV allocation while keeping the formal processing output intact.
- Cache settings now show voice-cache and sent-transfer-cache file counts and sizes.

- Replaced the primary Sync tab with a phone-transfer workflow that receives each
  LocalSend batch as a persistent task, records the original file baseline, scans
  generated/modified processing outputs, supports selection and preview, discovers
  nearby LocalSend devices, and streams selected results back to the phone.
- Added LocalSend Protocol v2.1 sender support with certificate-fingerprint
  verification, prepare/upload/cancel handling, progress, retryable failures, and
  persistent return history.
- Added transfer-session and artifact-diff services. Lyrics recognition, translation,
  online lyrics, vocal separation, and video aggregation now register outputs produced
  from received phone material, including outputs saved outside the receive directory.

### Changed

- The Model Library is now the single place for choosing ASR models. It includes
  an Online Recognition card for Groq and Xunfei plus selectable installed
  Whisper models. Preferences retain language, vocal-separation, and GPU settings
  without duplicating provider/model selectors.
- Saving credentials no longer silently switches the active ASR provider. Missing
  online credentials can be configured from the Model Library, which then returns
  to model selection.
- Xunfei recognition now falls back automatically from Speed Transcription to
  Streaming Dictation when the configured AppID returns license errors 11200 or
  11201. Streaming mode splits long audio into 50-second requests, runs up to four
  requests concurrently, and restores timestamps when merging the results.

### Fixed

- Xunfei Streaming Dictation now detects connections ended early by long
  intros/interludes. It retries unfinished audio in 8-second pieces below the
  service's endpoint-silence threshold instead of failing with
  `socket is already closed` or silently missing later vocals.
- Online Matching now uses one result area for both lyrics and artwork. “Search
  Lyrics” displays the lyrics table, while “Search Cover” displays a cover grid.
  The redundant “Write Audio Tags” button was removed; clicking an online cover or
  choosing a local image opens the existing confirmation step directly.
- The phone receiver now sends an explicit HTTP/1.1 success response before UI/session
  indexing callbacks, preventing LocalSend mobile clients from reporting a failed
  transfer after the file was already saved. Receive-directory controls are now
  separate “Open Folder” and “Choose Folder” buttons.
- Simplified the phone-transfer result toolbar: the redundant result filter was removed,
  only pending generated/modified differences are shown, and selection actions now sit
  beside the Pending Return directory.
- Successfully returned staging files are moved into the sent-transfer cache and
  disappear from the normal transfer list. Clearing application cache removes these
  archived return copies and voice recordings, but never pending files or formal outputs.
- Existing A/B bidirectional and mirror folder synchronization is preserved under a
  collapsed Advanced Folder Sync section. The main workflow no longer presents a
  misleading "phone folder path".
- LocalSend receiving now uses per-transfer directories, concurrent HTTP handling,
  expiring sessions, device discovery callbacks, and DER certificate fingerprints.

## 0.4.0 - 2026-07-16

### Fixed

- Vocal Separation enhancement controls now run real UVR DeNoise Lite and
  UVR DeEcho-DeReverb processing on the separated vocal track. The model
  library downloads and verifies both models, the worker streams every stage,
  and accompaniment-only output automatically disables vocal enhancement.
- Packaged enhancement now includes SciPy's lazy FFT module and libsamplerate,
  allowing the four-band DeEcho-DeReverb model to render in the Windows build;
  swallowed upstream errors are also surfaced with their actual cause.
- Online Matching and Vocal Separation no longer expose per-page output selectors or persist a
  device choice; both players bind to the current Windows system default and follow default-device
  changes while the application is running.
- Windows CI now reuses a preinstalled ffmpeg/ffprobe or downloads the compact Windows essentials
  archive directly, avoiding Chocolatey rate limits and oversized CI downloads.
- Demucs GPU selection now reuses the active external CUDA Worker's Torch in an isolated
  process, so an installed RTX/CUDA runtime is no longer hidden by the desktop bundle's CPU
  Torch. Progress identifies the actual GPU, and CPU/GPU processes remain isolated.
- Starting playback in Online Matching now pauses Vocal Separation playback and vice versa.
- A previously saved virtual ASL/streaming device no longer overrides an available physical
  speaker or headset after Windows changes its default output.
- Local lyric playback and the two-stem preview now expose the actual Windows output device,
  remember an explicit choice, avoid known virtual defaults when a physical speaker is available,
  rebind and unmute it immediately before playback, refresh after hot-plug, and report decoder
  errors instead of silently playing through the wrong device.
- Batch recognition, translation, and online matching now stream the current file, active
  stage, per-item result, overall progress, and final success/failure counts into the Batch
  workspace instead of showing most work only in the status bar after completion.
- Packaged Demucs processing now loads only the locally verified model repository instead of
  contacting Hugging Face again during separation; packaged diagnostics also retain pydub.
- Online Matching now uses a dedicated left workspace containing local and online lyrics
  side by side with the player below; the right tab is reserved for search results and
  recognition, apply, merge, and calibration controls.
- Clean CI/base installations now include the Requests dependency required while loading
  the Xunfei provider, while the optional Torch runtime is imported only when a local
  Whisper model is actually loaded; official checkout/setup actions now use Node 24.
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

- The audio model card now includes downloadable denoise and de-reverb models
  alongside Demucs, with installation state, progress, retry, and CPU/GPU reuse.
- Vocal Separation now switches the main content into a three-column material/real-time-lyrics/
  processing layout. The middle column reads the same local LRC shown on the left side of Online
  Matching and follows the separation playhead.
- The stem mixer adds a directly draggable waveform playhead, a dedicated Pause button, a 1x–10x
  cycling speed button, and true reverse preview rendered locally through ffmpeg.
- A top-level Model Library beside AI Mode and Help opens two white cards for text-recognition
  and audio-separation models. Each card includes its CPU/GPU-shared models and the matching
  GPU runtime status or configuration entry.
- A verified Demucs model catalog and real separation core that produces lossless vocal and
  accompaniment stems, reports processing stages, supports cancellation, and renders an
  independently volume-adjusted mix through the bundled ffmpeg.
- A unified searchable model library for local Whisper recognition and Demucs separation,
  including model purpose, speed, quality, size, installation state, verified downloads,
  retry, cancellation, and direct access from the main menu bar.
- A sixth right-side Vocal Separation workspace with processing settings above a synchronized
  two-waveform mixer, shared seek/playback, independent accompaniment/vocal volumes, and
  lossless export of the adjusted mix.
- A selectable-song Online Matching workspace with side-by-side editable local/online lyrics,
  four explicit keep/replace/cross-merge choices, and normalized timeline-to-text alignment.
- A local-media player beneath the comparison view that seeks, pauses, and independently
  highlights/bold-scrolls both lyric timelines at the current playback position.
- A fifth right-side Batch workspace consolidating batch recognition, batch translation,
  and thresholded LRCLIB matching, with optional backup-first application and a progress log.
- An F1 Help dialog with offline quick guides for local AI deployment, OpenAI-compatible
  endpoints, MCP write authorization, translation, and online lyric matching.
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

### Changed

- The selected material is shown in its own top box. Default Demucs model and CPU/GPU selection
  moved out of the processing form and into the Audio Separation card in Model Library.
- The vocal mixer now aligns accompaniment and vocal volume rows and uses one larger adjusted-
  result button. The upper form uses the material selected on the left, removes redundant
  material/mode rows, and can output both stems, vocals only, or accompaniment only.
- The existing “Enable Demucs vocal separation” recognition option now runs the selected
  local ASR against a temporary vocal stem and cleans all intermediate files, instead of
  being a saved but unused setting.
- LRCLIB candidates are converted from Traditional to Simplified Chinese before preview,
  merge, calibration, or batch application. AI calibration now uses the current edited left
  timeline, the current right reference text, and immediately refreshes the left result.
- Online Matching now builds a combined catalog from configured music and video libraries,
  labels and filters them by source, and places Start/Re-recognize beside Search LRCLIB.
- Batch translation now uses automatic per-file source-language detection and translates
  each LRC into the selected target language; AI and offline translation both accept Auto.

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
