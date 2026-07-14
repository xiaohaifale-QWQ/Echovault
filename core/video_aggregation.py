"""Create chronological video aggregates without altering source files."""

from __future__ import annotations

import csv
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .audio_utils import find_ffmpeg
from .lrc_parser import parse_lrc_file
from .process_utils import hidden_window_kwargs
from .video_library import AGGREGATE_DIRECTORY_PREFIX, scan_videos


@dataclass(frozen=True)
class VideoAggregateResult:
    output_dir: Path
    video_path: Path
    manifest_path: Path
    video_count: int
    reencoded: bool


def aggregate_videos_by_time(folder: str | Path, offset_seconds: int = 0) -> VideoAggregateResult:
    """Join every video under a folder into a chronologically ordered MP4."""
    root = Path(folder).expanduser().resolve()
    videos = scan_videos(root, offset_seconds=offset_seconds)
    if not videos:
        raise ValueError("当前文件夹中没有可汇总的视频素材")
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise RuntimeError("未找到 ffmpeg，无法汇总视频")

    output_dir = root / f"{AGGREGATE_DIRECTORY_PREFIX}{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = output_dir / "时间清单.csv"
    concat_path = output_dir / "视频拼接清单.txt"
    video_path = output_dir / "视频汇总.mp4"
    _write_manifest(manifest_path, videos)
    _write_concat_list(concat_path, videos)

    copy_command = [
        ffmpeg_path,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(video_path),
    ]
    if _run_ffmpeg(copy_command):
        return VideoAggregateResult(output_dir, video_path, manifest_path, len(videos), False)

    if video_path.exists():
        video_path.unlink()
    reencode_command = [
        ffmpeg_path,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(video_path),
    ]
    if not _run_ffmpeg(reencode_command):
        raise RuntimeError("视频汇总失败：视频编码不兼容，重新编码也未成功")
    return VideoAggregateResult(output_dir, video_path, manifest_path, len(videos), True)


def write_video_transcript_timeline(folder: str | Path, offset_seconds: int = 0) -> tuple[Path, int]:
    """Map each recognised video-LRC line to a calibrated real-world timestamp."""
    root = Path(folder).expanduser().resolve()
    output_path = root / "视频文字时间轴.csv"
    row_count = 0
    with output_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["视频文件", "视频相对时间", "对应日期时间", "识别文字"])
        for video in scan_videos(root, offset_seconds=offset_seconds):
            lrc_path = video.get("lrc_path")
            if not lrc_path:
                continue
            try:
                lrc = parse_lrc_file(lrc_path)
            except (OSError, UnicodeError):
                continue
            for line in sorted(lrc.lines, key=lambda item: item.timestamp):
                absolute_time = video["captured_at"] + timedelta(seconds=line.timestamp)
                writer.writerow(
                    [
                        video["path"],
                        f"{line.timestamp:.2f}",
                        absolute_time.strftime("%Y-%m-%d %H:%M:%S"),
                        line.text,
                    ]
                )
                row_count += 1
    return output_path, row_count


def _run_ffmpeg(command: list[str]) -> bool:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        **hidden_window_kwargs(),
    )
    return completed.returncode == 0


def _write_manifest(path: Path, videos: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["顺序", "文件", "校准后时间", "时间来源"])
        for index, video in enumerate(videos, 1):
            writer.writerow(
                [
                    index,
                    video["path"],
                    video["captured_at"].strftime("%Y-%m-%d %H:%M:%S"),
                    video["timestamp_source"],
                ]
            )


def _write_concat_list(path: Path, videos: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for video in videos:
            escaped = str(video["path"]).replace("'", r"'\''")
            output.write(f"file '{escaped}'\n")
