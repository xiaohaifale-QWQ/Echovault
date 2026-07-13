"""Shared music-library scanning and instrumental marker persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from core.audio_utils import SUPPORTED_FORMATS


INSTRUMENTAL_FILE_NAME = ".musicsync_instrumental.json"
INSTRUMENTAL_SCHEMA_VERSION = 1


class InstrumentalStore:
    """Store instrumental markers as paths relative to one library root."""

    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir).expanduser().resolve()
        self.path = self.root / INSTRUMENTAL_FILE_NAME
        self._marked = self._load()

    def _relative_key(self, file_path: str | Path) -> str:
        candidate = Path(file_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"文件不在音乐库中: {file_path}") from exc
        return relative.as_posix()

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return set()

        if isinstance(data, dict) and isinstance(data.get("instrumental"), list):
            raw_paths = data["instrumental"]
        elif isinstance(data, dict):
            # 兼容早期 CLI 写入的 {"绝对路径": true} 格式。
            raw_paths = [key for key, value in data.items() if value is True]
        else:
            raw_paths = []

        marked = set()
        for value in raw_paths:
            if not isinstance(value, str):
                continue
            try:
                marked.add(self._relative_key(value))
            except ValueError:
                continue
        return marked

    def is_marked(self, file_path: str | Path) -> bool:
        try:
            return self._relative_key(file_path) in self._marked
        except ValueError:
            return False

    def absolute_paths(self) -> set[str]:
        return {str((self.root / Path(key)).resolve()) for key in self._marked}

    def replace(self, file_paths: Iterable[str | Path]) -> None:
        self._marked = {self._relative_key(path) for path in file_paths}
        self._save()

    def set_marked(self, file_path: str | Path, marked: bool) -> None:
        key = self._relative_key(file_path)
        if marked:
            self._marked.add(key)
        else:
            self._marked.discard(key)
        self._save()

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": INSTRUMENTAL_SCHEMA_VERSION,
            "instrumental": sorted(self._marked),
        }
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)


def scan_audio(folder: str | Path) -> list[dict]:
    """Recursively scan a music directory and return normalized song records."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"音乐目录不存在: {root}")

    instrumental = InstrumentalStore(root)
    songs = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_FORMATS:
            continue
        resolved = path.resolve()
        lrc_path = resolved.with_suffix(".lrc")
        songs.append(
            {
                "path": str(resolved),
                "name": resolved.name,
                "folder": (
                    str(resolved.parent.relative_to(root)) if resolved.parent != root else ""
                ),
                "size": resolved.stat().st_size,
                "has_lrc": lrc_path.exists(),
                "lrc_path": str(lrc_path) if lrc_path.exists() else None,
                "instrumental": instrumental.is_marked(resolved),
            }
        )
    return sorted(songs, key=lambda song: (song["name"].casefold(), song["path"].casefold()))
