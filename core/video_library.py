"""Video material scanning and timestamp extraction."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .audio_utils import find_ffprobe
from .process_utils import hidden_window_kwargs

VIDEO_FORMATS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".mts",
    ".m2ts",
    ".webm",
    ".wmv",
}
AGGREGATE_DIRECTORY_PREFIX = "视频汇总_"


def _parse_creation_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _probe_creation_time(path: Path) -> datetime | None:
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        return None
    try:
        completed = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format_tags=creation_time:stream_tags=creation_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            **hidden_window_kwargs(),
        )
        metadata = json.loads(completed.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None

    candidates = [metadata.get("format", {}).get("tags", {}).get("creation_time")]
    candidates.extend(
        stream.get("tags", {}).get("creation_time")
        for stream in metadata.get("streams", [])
        if isinstance(stream, dict)
    )
    for value in candidates:
        parsed = _parse_creation_time(value)
        if parsed:
            return parsed
    return None


def video_timestamp(path: str | Path, offset_seconds: int = 0) -> tuple[datetime, str]:
    """Return a video timestamp and whether it came from metadata or the file."""
    resolved = Path(path).expanduser().resolve()
    captured_at = _probe_creation_time(resolved)
    source = "视频元数据"
    if captured_at is None:
        captured_at = datetime.fromtimestamp(resolved.stat().st_mtime)
        source = "文件修改时间"
    if offset_seconds:
        from datetime import timedelta

        captured_at += timedelta(seconds=offset_seconds)
    return captured_at, source


def calibration_offset_seconds(recorded_start: datetime, actual_start: datetime) -> int:
    """Return the offset that maps a video's recorded start time to real time."""
    return int((actual_start - recorded_start).total_seconds())


def scan_video_catalog(folder: str | Path) -> list[dict]:
    """Scan video paths for selectors without probing capture timestamps."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"视频素材文件夹不存在: {root}")
    videos = []
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.suffix.lower() not in VIDEO_FORMATS
            or any(
                parent.name.startswith(AGGREGATE_DIRECTORY_PREFIX)
                for parent in path.parents
            )
        ):
            continue
        resolved = path.resolve()
        lrc_path = resolved.with_suffix(".lrc")
        videos.append(
            {
                "path": str(resolved),
                "name": resolved.name,
                "material_type": "video",
                "folder": (
                    str(resolved.parent.relative_to(root))
                    if resolved.parent != root
                    else ""
                ),
                "size": resolved.stat().st_size,
                "has_lrc": lrc_path.exists(),
                "lrc_path": str(lrc_path) if lrc_path.exists() else None,
            }
        )
    return sorted(
        videos, key=lambda video: (video["name"].casefold(), video["path"].casefold())
    )


def scan_videos(folder: str | Path, offset_seconds: int = 0) -> list[dict]:
    """Recursively scan video material, excluding previous aggregate outputs."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"视频素材文件夹不存在: {root}")
    videos = []
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.suffix.lower() not in VIDEO_FORMATS
            or any(parent.name.startswith(AGGREGATE_DIRECTORY_PREFIX) for parent in path.parents)
        ):
            continue
        captured_at, source = video_timestamp(path, offset_seconds)
        resolved = path.resolve()
        lrc_path = resolved.with_suffix(".lrc")
        videos.append(
            {
                "path": str(resolved),
                "name": resolved.name,
                "material_type": "video",
                "folder": str(resolved.parent.relative_to(root)) if resolved.parent != root else "",
                "size": resolved.stat().st_size,
                "captured_at": captured_at,
                "timestamp_source": source,
                "has_lrc": lrc_path.exists(),
                "lrc_path": str(lrc_path) if lrc_path.exists() else None,
            }
        )
    return sorted(videos, key=lambda video: (video["captured_at"], video["name"].casefold()))
