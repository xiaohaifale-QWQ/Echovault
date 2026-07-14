"""Local cache management for AI voice-input recordings."""

from __future__ import annotations

import shutil
import wave
from datetime import datetime
from pathlib import Path


def voice_cache_dir(cache_root: str | Path | None = None) -> Path:
    """Return the app-owned cache directory, creating it when needed."""
    root = (
        Path(cache_root)
        if cache_root is not None
        else Path.home() / ".music-lyrics-sync" / "cache"
    )
    directory = root / "voice-input"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def new_recording_path(cache_root: str | Path | None = None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return voice_cache_dir(cache_root) / f"voice_{timestamp}.wav"


def pcm_to_wav(
    raw_path: str | Path,
    wav_path: str | Path,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> Path:
    """Wrap a temporary PCM capture in a standard WAV container."""
    raw = Path(raw_path)
    output = Path(wav_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        with raw.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                wav_file.writeframesraw(chunk)
    return output


def clear_voice_cache(cache_root: str | Path | None = None) -> int:
    """Delete only cached voice recordings and return the number of removed entries."""
    directory = voice_cache_dir(cache_root)
    removed = 0
    for item in directory.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removed += 1
    return removed
