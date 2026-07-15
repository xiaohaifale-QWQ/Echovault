"""LRCLIB search, safe LRC replacement, comparison, and AI calibration."""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from core.ai_assistant import AISettings, complete
from core.lyrics_translation import timed_text_positions

LRCLIB_API_BASE = "https://lrclib.net/api"
LRCLIB_USER_AGENT = "Echovault/0.3.0 (https://github.com/xiaohaifale-QWQ/Echovault)"
_TIMESTAMP_PREFIX = re.compile(r"^(?:\[\d{1,3}:\d{2}(?:\.\d{2,3})?\])+\s*")
_METADATA_LINE = re.compile(r"^\[[A-Za-z]+:.*\]$")


@dataclass(frozen=True)
class LyricsMatch:
    record_id: int
    track_name: str
    artist_name: str
    album_name: str
    duration: float
    instrumental: bool
    plain_lyrics: str
    synced_lyrics: str
    score: float = 0.0

    @property
    def has_synced_lyrics(self) -> bool:
        return bool(self.synced_lyrics.strip())


@dataclass(frozen=True)
class MediaSearchMetadata:
    track_name: str
    artist_name: str = ""
    album_name: str = ""
    duration: float = 0.0


def _record_from_payload(payload: Any) -> LyricsMatch | None:
    if not isinstance(payload, dict):
        return None
    try:
        record_id = int(payload["id"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        duration = float(payload.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return LyricsMatch(
        record_id=record_id,
        track_name=str(payload.get("trackName") or "").strip(),
        artist_name=str(payload.get("artistName") or "").strip(),
        album_name=str(payload.get("albumName") or "").strip(),
        duration=duration,
        instrumental=bool(payload.get("instrumental", False)),
        plain_lyrics=str(payload.get("plainLyrics") or ""),
        synced_lyrics=str(payload.get("syncedLyrics") or ""),
    )


def _request_json(url: str, *, timeout: float = 20.0, opener=None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": LRCLIB_USER_AGENT})
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"LRCLIB 返回 HTTP {exc.code}。") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 LRCLIB：{exc.reason}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("LRCLIB 返回了无法解析的响应。") from exc


def _match_score(
    match: LyricsMatch,
    *,
    track_name: str,
    artist_name: str,
    duration: float,
) -> float:
    score = SequenceMatcher(None, track_name.casefold(), match.track_name.casefold()).ratio() * 60
    if artist_name:
        score += (
            SequenceMatcher(None, artist_name.casefold(), match.artist_name.casefold()).ratio()
            * 25
        )
    else:
        score += 12.5
    if duration > 0 and match.duration > 0:
        score += max(0.0, 10.0 - abs(duration - match.duration) * 2)
    if match.has_synced_lyrics:
        score += 5
    return min(100.0, score)


def search_lrclib(
    track_name: str,
    *,
    artist_name: str = "",
    album_name: str = "",
    duration: float = 0.0,
    timeout: float = 20.0,
    opener=None,
) -> list[LyricsMatch]:
    if not track_name.strip():
        raise ValueError("搜索歌名不能为空。")
    query = {"track_name": track_name.strip()}
    if artist_name.strip():
        query["artist_name"] = artist_name.strip()
    if album_name.strip():
        query["album_name"] = album_name.strip()
    payload = _request_json(
        f"{LRCLIB_API_BASE}/search?{urllib.parse.urlencode(query)}",
        timeout=timeout,
        opener=opener,
    )
    if not isinstance(payload, list):
        return []
    matches = []
    for item in payload:
        match = _record_from_payload(item)
        if match is None:
            continue
        matches.append(
            replace(
                match,
                score=_match_score(
                    match,
                    track_name=track_name,
                    artist_name=artist_name,
                    duration=duration,
                ),
            )
        )
    return sorted(matches, key=lambda item: item.score, reverse=True)


def select_best_synced_match(
    matches: list[LyricsMatch], *, minimum_score: float = 80.0
) -> LyricsMatch | None:
    """Return the highest-scoring synchronized match above a safety threshold."""
    candidates = [
        match
        for match in matches
        if match.has_synced_lyrics and match.score >= minimum_score
    ]
    return max(candidates, key=lambda item: item.score, default=None)


def get_lrclib_record(record_id: int, *, timeout: float = 20.0, opener=None) -> LyricsMatch:
    payload = _request_json(
        f"{LRCLIB_API_BASE}/get/{int(record_id)}", timeout=timeout, opener=opener
    )
    match = _record_from_payload(payload)
    if match is None:
        raise RuntimeError(f"LRCLIB 中不存在记录 {record_id}。")
    return match


def media_search_metadata(media_path: str | Path) -> MediaSearchMetadata:
    path = Path(media_path)
    stem = path.stem
    artist_name = ""
    track_name = stem
    if " - " in stem:
        artist_name, track_name = (part.strip() for part in stem.split(" - ", 1))
    album_name = ""
    duration = 0.0
    try:
        import mutagen

        media = mutagen.File(path, easy=True)
        if media is not None:
            tags = media.tags or {}

            def first_tag(name: str, fallback: str = "") -> str:
                value = tags.get(name)
                if isinstance(value, (list, tuple)) and value:
                    return str(value[0]).strip()
                return str(value).strip() if value else fallback

            track_name = first_tag("title", track_name)
            artist_name = first_tag("artist", artist_name)
            album_name = first_tag("album", album_name)
            duration = float(getattr(media.info, "length", 0.0) or 0.0)
    except (OSError, TypeError, ValueError, mutagen.MutagenError):
        pass
    if duration <= 0 and path.is_file():
        try:
            from core.audio_utils import get_audio_info

            duration = float(get_audio_info(str(path)).get("duration", 0.0))
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    return MediaSearchMetadata(track_name, artist_name, album_name, duration)


def _reference_lines(reference_lyrics: str) -> list[str]:
    lines = []
    for raw_line in reference_lyrics.splitlines():
        text = _TIMESTAMP_PREFIX.sub("", raw_line).strip()
        if text and not _METADATA_LINE.match(text):
            lines.append(text)
    return lines


def compare_lyrics(local_content: str, reference_lyrics: str) -> dict[str, float | int]:
    _, _, local_lines = timed_text_positions(local_content)
    reference_lines = _reference_lines(reference_lyrics)
    local_text = "\n".join(local_lines).casefold()
    reference_text = "\n".join(reference_lines).casefold()
    similarity = SequenceMatcher(None, local_text, reference_text).ratio() if reference_text else 0
    return {
        "similarity": similarity,
        "local_lines": len(local_lines),
        "reference_lines": len(reference_lines),
    }


def _next_backup_path(path: Path) -> Path:
    base = path.with_suffix(path.suffix + ".bak")
    if not base.exists():
        return base
    index = 1
    while True:
        candidate = path.with_suffix(path.suffix + f".bak.{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _atomic_replace_with_backup(path: Path, content: str) -> Path | None:
    backup_path = None
    if path.exists():
        backup_path = _next_backup_path(path)
        shutil.copy2(path, backup_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content.rstrip("\r\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)
    return backup_path


def apply_synced_lyrics(lrc_path: str | Path, match: LyricsMatch) -> tuple[Path, Path | None]:
    if not match.has_synced_lyrics:
        raise RuntimeError("所选 LRCLIB 记录没有同步时间轴歌词。")
    _, _, timed_lines = timed_text_positions(match.synced_lyrics)
    if not timed_lines:
        raise RuntimeError("所选 LRCLIB 同步歌词没有有效时间戳。")
    path = Path(lrc_path)
    backup = _atomic_replace_with_backup(path, match.synced_lyrics)
    return path, backup


def _decode_corrections(response: str, expected_count: int) -> list[str]:
    start = response.find("{")
    end = response.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("AI 校准没有返回 JSON 对象。")
    try:
        payload = json.loads(response[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI 校准返回了无效 JSON。") from exc
    corrections = payload.get("corrections") if isinstance(payload, dict) else None
    if (
        not isinstance(corrections, list)
        or len(corrections) != expected_count
        or not all(isinstance(item, str) for item in corrections)
    ):
        raise RuntimeError("AI 校准返回的行数与本地时间轴不一致，未写入文件。")
    return [item.strip() for item in corrections]


def calibrate_lrc_with_reference(
    lrc_path: str | Path,
    reference_lyrics: str,
    *,
    ai_settings: AISettings,
    track_name: str = "",
    artist_name: str = "",
    calibrator=None,
) -> tuple[Path, Path]:
    path = Path(lrc_path)
    content = path.read_text(encoding="utf-8")
    raw_lines, positions, local_lines = timed_text_positions(content)
    reference_lines = _reference_lines(reference_lyrics)
    if not local_lines:
        raise RuntimeError("本地 LRC 没有可校准的时间轴歌词。")
    if not reference_lines:
        raise RuntimeError("所选在线记录没有可用于校准的歌词文字。")
    if calibrator is not None:
        corrections = list(calibrator(local_lines, reference_lines))
    else:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是歌词校准器。参考公开歌词修正本地 ASR 的错字和漏词，但不得改变行数、"
                    "合并行或拆分行。严格返回 JSON：{\"corrections\":[\"第1行\",\"第2行\"]}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "track": track_name,
                        "artist": artist_name,
                        "local_timeline_lines": local_lines,
                        "reference_lyrics_lines": reference_lines,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        response = complete(ai_settings, messages, temperature=0.0)
        corrections = _decode_corrections(response, len(local_lines))
    if len(corrections) != len(positions):
        raise RuntimeError("校准结果行数与本地时间轴不一致，未写入文件。")
    for line_index, correction in zip(positions, corrections):
        match = re.match(
            r"^(?P<prefix>(?:\[\d{1,3}:\d{2}(?:\.\d{2,3})?\])+)",
            raw_lines[line_index],
        )
        raw_lines[line_index] = match.group("prefix") + str(correction).strip()
    backup = _atomic_replace_with_backup(path, "\n".join(raw_lines))
    if backup is None:
        raise RuntimeError("校准要求本地 LRC 已存在。")
    return path, backup
