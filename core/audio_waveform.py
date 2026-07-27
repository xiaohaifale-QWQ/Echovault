"""Generate compact waveform peak data for the desktop editor."""

from __future__ import annotations

import array
import math
import subprocess
import sys
import wave
from pathlib import Path

from core.audio_utils import find_ffmpeg
from core.process_utils import hidden_window_kwargs


def _extract_pcm_wav_peaks(
    source: Path,
    point_count: int,
) -> list[tuple[float, float]]:
    """Read common PCM WAV files when an external FFmpeg binary is unavailable."""

    try:
        with wave.open(str(source), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            frame_count = audio.getnframes()
            if channels <= 0 or sample_width not in {1, 2, 3, 4} or frame_count <= 0:
                return []
            frames_per_bucket = max(1, math.ceil(frame_count / max(1, point_count)))
            scale = float(1 << (sample_width * 8 - 1))
            frame_width = channels * sample_width
            peaks: list[tuple[float, float]] = []
            while True:
                data = audio.readframes(frames_per_bucket)
                if not data:
                    break
                frames = len(data) // frame_width
                sample_step = max(1, frames // 128)
                minimum = 1.0
                maximum = -1.0
                for frame_index in range(0, frames, sample_step):
                    offset = frame_index * frame_width
                    channel_values = []
                    for channel in range(channels):
                        start = offset + channel * sample_width
                        raw = data[start : start + sample_width]
                        if sample_width == 1:
                            value = raw[0] - 128
                        else:
                            value = int.from_bytes(raw, "little", signed=True)
                        channel_values.append(value / scale)
                    sample = sum(channel_values) / len(channel_values)
                    minimum = min(minimum, sample)
                    maximum = max(maximum, sample)
                peaks.append((minimum, maximum))
            return peaks
    except (OSError, EOFError, wave.Error) as exc:
        raise RuntimeError(f"无法读取 WAV 波形：{source}") from exc


def extract_waveform_peaks(
    file_path: str | Path,
    *,
    point_count: int = 4000,
    sample_rate: int = 4000,
) -> list[tuple[float, float]]:
    """Decode any FFmpeg-supported media into normalized min/max peak buckets."""
    source = Path(file_path)
    if not source.is_file():
        raise FileNotFoundError(f"素材不存在：{source}")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        if source.suffix.casefold() == ".wav":
            return _extract_pcm_wav_peaks(source, point_count)
        raise RuntimeError("未找到 ffmpeg，无法生成音频波形。")
    completed = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ],
        capture_output=True,
        timeout=180,
        check=False,
        **hidden_window_kwargs(),
    )
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "ffmpeg 没有返回可用的波形数据。")

    samples = array.array("h")
    samples.frombytes(completed.stdout[: len(completed.stdout) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return []

    bucket_size = max(1, math.ceil(len(samples) / max(1, point_count)))
    scale = 32768.0
    peaks: list[tuple[float, float]] = []
    for start in range(0, len(samples), bucket_size):
        bucket = samples[start : start + bucket_size]
        peaks.append((min(bucket) / scale, max(bucket) / scale))
    return peaks
