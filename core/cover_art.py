"""MusicBrainz/Cover Art Archive search and safe cover downloads."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
COVER_ART_API_BASE = "https://coverartarchive.org"
COVER_USER_AGENT = (
    "Echovault/0.4.0 (https://github.com/xiaohaifale-QWQ/Echovault)"
)
MAX_COVER_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class CoverArtMatch:
    release_group_id: str
    title: str
    artist_name: str
    first_release_date: str
    score: float
    image_url: str
    thumbnail_url: str
    source: str = "MusicBrainz / Cover Art Archive"


def _artist_credit_text(credits: object) -> str:
    if not isinstance(credits, list):
        return ""
    return "".join(
        str(item.get("name", "")) + str(item.get("joinphrase", ""))
        for item in credits
        if isinstance(item, dict)
    ).strip()


def _lucene_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _https_url(value: object) -> str:
    url = str(value or "")
    return "https://" + url[7:] if url.startswith("http://") else url


def _request_json(
    url: str,
    *,
    timeout: float,
    opener: Callable = urllib.request.urlopen,
    allow_not_found: bool = False,
) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": COVER_USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if allow_not_found and exc.code == 404:
            return {}
        if exc.code == 503:
            raise RuntimeError("在线封面服务繁忙，请稍后再试。") from exc
        raise RuntimeError(f"在线封面服务返回 HTTP {exc.code}。") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接在线封面服务：{exc.reason}") from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("在线封面服务返回了无法解析的数据。") from exc
    return decoded if isinstance(decoded, dict) else {}


def _release_group_candidates(payload: dict) -> list[dict]:
    groups = payload.get("release-groups", [])
    return [group for group in groups if isinstance(group, dict)]


def _recording_release_groups(payload: dict) -> list[dict]:
    groups: list[dict] = []
    seen: set[str] = set()
    for recording in payload.get("recordings", []):
        if not isinstance(recording, dict):
            continue
        for release in recording.get("releases", []):
            if not isinstance(release, dict):
                continue
            group = release.get("release-group", {})
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id", ""))
            if not group_id or group_id in seen:
                continue
            seen.add(group_id)
            groups.append(
                {
                    "id": group_id,
                    "title": group.get("title") or release.get("title") or "",
                    "score": recording.get("score", 0),
                    "first-release-date": recording.get("first-release-date", ""),
                    "artist-credit": recording.get("artist-credit", []),
                }
            )
    return groups


def _search_musicbrainz_groups(
    track_name: str,
    artist_name: str,
    album_name: str,
    *,
    limit: int,
    timeout: float,
    opener: Callable,
) -> list[dict]:
    title = album_name.strip() or track_name.strip()
    query = f"releasegroup:{_lucene_literal(title)}"
    if artist_name.strip():
        query += f" AND artist:{_lucene_literal(artist_name.strip())}"
    url = (
        f"{MUSICBRAINZ_API_BASE}/release-group/?"
        + urllib.parse.urlencode(
            {"query": query, "fmt": "json", "limit": min(100, max(limit * 2, 8))}
        )
    )
    groups = _release_group_candidates(
        _request_json(url, timeout=timeout, opener=opener)
    )
    if groups or not track_name.strip():
        return groups

    recording_query = f"recording:{_lucene_literal(track_name.strip())}"
    if artist_name.strip():
        recording_query += f" AND artist:{_lucene_literal(artist_name.strip())}"
    recording_url = (
        f"{MUSICBRAINZ_API_BASE}/recording/?"
        + urllib.parse.urlencode(
            {
                "query": recording_query,
                "fmt": "json",
                "limit": min(100, max(limit * 2, 8)),
            }
        )
    )
    return _recording_release_groups(
        _request_json(recording_url, timeout=timeout, opener=opener)
    )


def search_cover_art(
    track_name: str,
    *,
    artist_name: str = "",
    album_name: str = "",
    limit: int = 6,
    timeout: float = 20.0,
    opener: Callable = urllib.request.urlopen,
) -> list[CoverArtMatch]:
    """Search release-group covers and return only candidates with actual artwork."""
    if not track_name.strip() and not album_name.strip():
        return []
    groups = _search_musicbrainz_groups(
        track_name,
        artist_name,
        album_name,
        limit=limit,
        timeout=timeout,
        opener=opener,
    )
    unique_groups: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        group_id = str(group.get("id", ""))
        if not group_id or group_id in seen:
            continue
        seen.add(group_id)
        unique_groups.append(group)
        if len(unique_groups) >= max(limit * 2, 8):
            break

    def cover_metadata(group: dict) -> dict:
        group_id = str(group.get("id", ""))
        return _request_json(
            f"{COVER_ART_API_BASE}/release-group/{group_id}/",
            timeout=timeout,
            opener=opener,
            allow_not_found=True,
        )

    if unique_groups:
        with ThreadPoolExecutor(max_workers=min(6, len(unique_groups))) as executor:
            metadata_results = list(executor.map(cover_metadata, unique_groups))
    else:
        metadata_results = []

    matches: list[CoverArtMatch] = []
    for group, metadata in zip(unique_groups, metadata_results):
        group_id = str(group.get("id", ""))
        images = [
            image
            for image in metadata.get("images", [])
            if isinstance(image, dict)
        ]
        if not images:
            continue
        image = next((item for item in images if item.get("front")), images[0])
        thumbnails = image.get("thumbnails", {})
        if not isinstance(thumbnails, dict):
            thumbnails = {}
        image_url = _https_url(
            thumbnails.get("1200")
            or thumbnails.get("500")
            or image.get("image")
            or ""
        )
        thumbnail_url = _https_url(
            thumbnails.get("500")
            or thumbnails.get("250")
            or thumbnails.get("small")
            or image_url
        )
        if not image_url:
            continue
        matches.append(
            CoverArtMatch(
                release_group_id=group_id,
                title=str(group.get("title", "")),
                artist_name=_artist_credit_text(group.get("artist-credit", [])),
                first_release_date=str(group.get("first-release-date", "")),
                score=float(group.get("score") or 0),
                image_url=image_url,
                thumbnail_url=thumbnail_url,
            )
        )
        if len(matches) >= limit:
            break
    return matches


def image_mime_type(data: bytes, fallback: str = "") -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return fallback.split(";", 1)[0].strip().lower()


def download_cover_art(
    url: str,
    *,
    timeout: float = 30.0,
    opener: Callable = urllib.request.urlopen,
    max_bytes: int = MAX_COVER_BYTES,
) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": COVER_USER_AGENT,
            "Accept": "image/jpeg,image/png",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            data = response.read()
            headers = getattr(response, "headers", None)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"下载封面失败，HTTP {exc.code}。") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法下载封面：{exc.reason}") from exc
    if not data:
        raise RuntimeError("下载到的封面为空。")
    if len(data) > max_bytes:
        raise RuntimeError("封面文件过大，请选择 20 MB 以内的图片。")
    content_type = ""
    if headers is not None:
        try:
            content_type = headers.get_content_type()
        except AttributeError:
            content_type = str(headers.get("Content-Type", ""))
    mime_type = image_mime_type(data, content_type)
    if mime_type not in {"image/jpeg", "image/png"}:
        raise RuntimeError("封面必须是 JPEG 或 PNG 图片。")
    return data, mime_type
