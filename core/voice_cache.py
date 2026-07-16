"""Local cache management for AI voice-input recordings."""

from __future__ import annotations

import shutil
import wave
from datetime import datetime
from pathlib import Path


def app_cache_dir(cache_root: str | Path | None = None) -> Path:
    root = (
        Path(cache_root)
        if cache_root is not None
        else Path.home() / ".music-lyrics-sync" / "cache"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def voice_cache_dir(cache_root: str | Path | None = None) -> Path:
    """Return the app-owned cache directory, creating it when needed."""
    directory = app_cache_dir(cache_root) / "voice-input"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def sent_transfer_cache_dir(cache_root: str | Path | None = None) -> Path:
    directory = app_cache_dir(cache_root) / "sent-transfer"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _directory_stats(directory: Path) -> tuple[int, int]:
    count = 0
    size = 0
    if directory.exists():
        for path in directory.rglob("*"):
            if path.is_file():
                count += 1
                size += path.stat().st_size
    return count, size


def cache_stats(cache_root: str | Path | None = None) -> dict[str, int]:
    voice_count, voice_size = _directory_stats(voice_cache_dir(cache_root))
    sent_count, sent_size = _directory_stats(sent_transfer_cache_dir(cache_root))
    return {
        "voice_count": voice_count,
        "voice_size": voice_size,
        "sent_count": sent_count,
        "sent_size": sent_size,
        "total_count": voice_count + sent_count,
        "total_size": voice_size + sent_size,
    }


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


def clear_sent_transfer_cache(cache_root: str | Path | None = None) -> int:
    directory = sent_transfer_cache_dir(cache_root)
    count, _size = _directory_stats(directory)
    for item in directory.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    return count


def clear_app_cache(cache_root: str | Path | None = None) -> dict[str, int]:
    before = cache_stats(cache_root)
    clear_voice_cache(cache_root)
    clear_sent_transfer_cache(cache_root)
    return before
