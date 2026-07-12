# Echovault

AI lyrics recognition + cross-device file sync | WIP

## Features

### AI Lyrics Recognition
- Groq Whisper API (cloud, free) and local OpenAI Whisper (offline)
- Chinese primary, supports English/Japanese/Korean
- LRC timeline lyrics output
- Batch processing with progress bar
- LRC lyrics editor (row edit, time offset, merge/split)
- Demucs vocal separation (optional)
- Traditional to Simplified Chinese conversion (OpenCC)
- Auto-detect instrumental music

### Song Management
- MP3/FLAC/WAV/AAC/M4A/OGG support
- Dual filters: lyrics status + file format
- Search, double-click rename (auto renames LRC too)
- Right-click mark as instrumental

### File Sync
- LocalSend Protocol v2.1 receiver (HTTPS + mDNS)
- Folder comparison + diff visualization
- Phone browser download via HTTP

### Model Download
- Download from GitHub Releases (China-accessible)
- Auto-detect cached models
- Real-time speed + ETA progress bar
- Supports tiny/base/small/medium

## Install

```bash
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault
pip install -r requirements.txt
```

Optional:
```bash
pip install groq              # cloud recognition
pip install openai-whisper     # local offline
pip install demucs             # vocal separation
```

## Usage

```bash
python main.py                 # GUI
python main.py transcribe ./   # CLI batch
```

First run: Settings -> Enter Groq API Key, or switch to Local Whisper -> Download Model.

## Phone Sync
1. Switch to Sync tab
2. Click "Enable LocalSend Receiver"
3. Open LocalSend app on phone, find "MusicSync" device, send files

## Tech Stack

| Layer | Tech |
|-------|------|
| ASR | Groq Whisper API / OpenAI Whisper |
| Audio | ffmpeg + pydub |
| Metadata | mutagen |
| GUI | PyQt6 |
| Sync | LocalSend Protocol v2.1 |

## Dev Status

- [x] AI recognition (Groq + local)
- [x] LRC parse/generate/edit
- [x] Batch queue + progress
- [x] Song filters, search, rename
- [x] Instrumental marking
- [x] LocalSend receiver (HTTPS)
- [x] Folder compare/sync
- [x] Model downloader
- [x] PyQt6 GUI
- [ ] Mobile app
- [ ] Standalone exe packaging
- [ ] AI lyrics translation

## Refs

- [OpenAI Whisper](https://github.com/openai/whisper)
- [LocalSend](https://github.com/localsend/localsend)
- [LDDC](https://github.com/chenmozhijin/LDDC)

## License

MIT
