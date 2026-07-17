"""Generate compact waveform peak data for the desktop editor."""

from __future__ import annotations

import array
import math
import subprocess
import sys
from pathlib import Path

from core.audio_utils import find_ffmpeg
from core.process_utils import hidden_window_kwargs


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
