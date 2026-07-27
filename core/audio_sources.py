"""Audio-source import, catalog search and download helpers.

Two source formats are supported:

* ``rest``: Echovault's small declarative JSON/REST contract.
* ``lx_js``: LX Music custom-source JavaScript.  The script is executed only
  in a short-lived Node VM worker and is used to resolve a selected song URL.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from core.output_paths import unique_output_path

USER_AGENT = "Echovault/0.7 AudioSource"
MAX_CATALOG_RESPONSE = 4 * 1024 * 1024
MAX_LX_SCRIPT_SIZE = 4 * 1024 * 1024
SUPPORTED_QUALITIES = ("128k", "320k", "flac", "flac24bit")
LX_PLATFORM_NAMES = {
    "kw": "酷我音乐",
    "kg": "酷狗音乐",
    "tx": "QQ音乐",
    "wy": "网易云音乐",
    "mg": "咪咕音乐",
    "local": "本地音乐",
}
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LX_META = re.compile(
    r"^\s*(?:/\*+|\*+|//)?\s*@(?P<key>name|description|version|author|homepage)"
    r"\s+(?P<value>.+?)\s*(?:\*/)?$",
    re.MULTILINE | re.IGNORECASE,
)


def _is_allowed_url(value: str, allow_remote_http: bool = False) -> bool:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    if parsed.scheme != "http" or not parsed.netloc:
        return False
    return allow_remote_http or (parsed.hostname or "").casefold() in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def parse_lx_source_metadata(script: str) -> dict[str, str]:
    """Read the userscript-style metadata header used by LX source files."""

    values = {
        match.group("key").casefold(): match.group("value").strip()
        for match in _LX_META.finditer(script[:16000])
    }
    return {
        "name": values.get("name", "LX 自定义音源"),
        "description": values.get("description", ""),
        "version": values.get("version", ""),
        "author": values.get("author", ""),
        "homepage": values.get("homepage", ""),
    }


def _lx_worker_path() -> Path:
    return Path(__file__).with_name("lx_source_worker.js")


def _run_lx_worker(payload: dict, timeout: int = 35) -> dict:
    node = shutil.which("node")
    if not node:
        raise ValueError("未找到 Node.js，无法加载 LX JS 音源。")
    worker = _lx_worker_path()
    if not worker.exists():
        raise ValueError("LX 音源兼容组件缺失。")
    command = [node, "--max-old-space-size=128", str(worker)]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() in {"path", "systemroot", "windir", "comspec", "temp", "tmp"}
    }
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
            creationflags=creationflags,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("加载 JS 音源超时，请检查音源服务是否可用。") from exc
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip()[-500:]
        raise ValueError(f"JS 音源运行失败。{detail}") from exc
    if not response.get("ok"):
        raise ValueError(str(response.get("error") or "JS 音源运行失败。"))
    value = response.get("value")
    if not isinstance(value, dict):
        raise ValueError("JS 音源返回了无效结果。")
    return value


def inspect_lx_source_script(path: str | Path) -> dict:
    """Load and inspect an LX source in the isolated compatibility worker."""

    source_path = Path(path)
    if source_path.suffix.casefold() != ".js":
        raise ValueError("请选择 .js 格式的 LX 音源文件。")
    size = source_path.stat().st_size
    if size <= 0 or size > MAX_LX_SCRIPT_SIZE:
        raise ValueError("JS 音源文件为空或超过 4 MB。")
    try:
        script = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("JS 音源必须使用 UTF-8 编码。") from exc
    metadata = parse_lx_source_metadata(script)
    inspected = _run_lx_worker(
        {"action": "inspect", "script": script, "metadata": metadata}
    )
    return {
        "metadata": metadata,
        "sources": inspected.get("sources", {}),
        "script": script,
    }


def import_lx_source(
    path: str | Path,
    storage_dir: str | Path | None = None,
) -> list[dict]:
    """Validate, copy and expand one LX script into platform configurations."""

    inspected = inspect_lx_source_script(path)
    script = inspected.pop("script")
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    target_dir = Path(storage_dir or Path.home() / ".music-lyrics-sync" / "audio-sources")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"lx-{digest[:16]}.js"
    if not target.exists() or target.read_text(encoding="utf-8") != script:
        temp = target.with_suffix(".js.tmp")
        temp.write_text(script, encoding="utf-8", newline="\n")
        temp.replace(target)

    metadata = inspected["metadata"]
    imported: list[dict] = []
    for source_key, details in inspected["sources"].items():
        if "musicUrl" not in details.get("actions", []):
            continue
        platform_name = details.get("name") or LX_PLATFORM_NAMES.get(source_key, source_key)
        raw = {
            "schema_version": 2,
            "type": "lx_js",
            "id": f"lx-{digest[:12]}-{source_key}",
            "name": f"{metadata['name']} · {platform_name}",
            "script_path": str(target),
            "script_sha256": digest,
            "source_key": source_key,
            "platform_name": platform_name,
            "qualities": details.get("qualitys", []),
            "metadata": metadata,
            "authorized": True,
            "enabled": True,
        }
        imported.append(validate_source_config(raw))
    if not imported:
        raise ValueError("该 JS 音源没有提供可用的歌曲地址解析功能。")
    return imported


def validate_source_config(raw: dict) -> dict:
    """Validate and normalize one REST or LX source configuration."""

    if not isinstance(raw, dict):
        raise ValueError("音源配置必须是 JSON 对象。")
    if raw.get("type") == "lx_js":
        source_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        script_path = str(raw.get("script_path", "")).strip()
        source_key = str(raw.get("source_key", "")).strip()
        if not source_id or not re.fullmatch(r"[A-Za-z0-9._-]{2,80}", source_id):
            raise ValueError("JS 音源 ID 无效。")
        if not name or not script_path or not source_key:
            raise ValueError("JS 音源配置缺少名称、脚本或平台。")
        if Path(script_path).suffix.casefold() != ".js":
            raise ValueError("JS 音源脚本路径无效。")
        qualities = [
            str(value)
            for value in raw.get("qualities", [])
            if str(value) in SUPPORTED_QUALITIES
        ]
        if not qualities:
            qualities = ["128k"]
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "schema_version": 2,
            "type": "lx_js",
            "id": source_id,
            "name": name,
            "script_path": script_path,
            "script_sha256": str(raw.get("script_sha256", "")),
            "source_key": source_key,
            "platform_name": str(
                raw.get("platform_name") or LX_PLATFORM_NAMES.get(source_key, source_key)
            ),
            "qualities": list(dict.fromkeys(qualities)),
            "metadata": {
                key: str(metadata.get(key, ""))
                for key in ("name", "description", "version", "author", "homepage")
            },
            "authorized": True,
            "enabled": bool(raw.get("enabled", True)),
        }

    name = str(raw.get("name", "")).strip()
    source_id = str(raw.get("id", "")).strip()
    base_url = str(raw.get("base_url", "")).strip().rstrip("/")
    search_path = str(raw.get("search_path", "")).strip()
    resolve_path = str(raw.get("resolve_path", "")).strip()
    terms_url = str(raw.get("terms_url", "")).strip()
    if not name:
        raise ValueError("音源名称不能为空。")
    if not source_id or not re.fullmatch(r"[A-Za-z0-9._-]{2,64}", source_id):
        raise ValueError("音源 ID 只能包含字母、数字、点、横线或下划线。")
    if not _is_allowed_url(base_url):
        raise ValueError("音源接口必须使用 HTTPS；本机服务可使用 localhost HTTP。")
    if not search_path or "{query}" not in search_path:
        raise ValueError("搜索路径必须包含 {query} 占位符。")
    if search_path.startswith(("http://", "https://")):
        raise ValueError("搜索路径必须相对于音源接口地址。")
    if resolve_path.startswith(("http://", "https://")):
        raise ValueError("解析路径必须相对于音源接口地址。")
    if resolve_path and "{id}" not in resolve_path:
        raise ValueError("解析路径必须包含 {id} 占位符。")
    if terms_url and not _is_allowed_url(terms_url):
        raise ValueError("授权说明链接必须使用 HTTPS。")
    if not bool(raw.get("authorized", False)):
        raise ValueError("必须确认你有权访问和下载该音源。")
    qualities = [
        str(value)
        for value in raw.get("qualities", ["128k", "320k", "flac"])
        if str(value) in SUPPORTED_QUALITIES
    ] or ["128k"]
    headers = raw.get("headers", {})
    clean_headers = (
        {
            str(key).strip(): str(value).strip()
            for key, value in headers.items()
            if isinstance(key, str) and isinstance(value, str) and key.strip()
        }
        if isinstance(headers, dict)
        else {}
    )
    return {
        "schema_version": 1,
        "type": "rest",
        "id": source_id,
        "name": name,
        "base_url": base_url,
        "search_path": search_path,
        "resolve_path": resolve_path,
        "qualities": list(dict.fromkeys(qualities)),
        "headers": clean_headers,
        "terms_url": terms_url,
        "authorized": True,
        "enabled": bool(raw.get("enabled", True)),
    }


def _endpoint(source: dict, path_template: str, **values: str) -> str:
    encoded = {
        key: urllib.parse.quote(str(value), safe="") for key, value in values.items()
    }
    path = path_template.format(**encoded)
    url = urllib.parse.urljoin(source["base_url"] + "/", path.lstrip("/"))
    if not _is_allowed_url(url):
        raise ValueError("音源返回了不允许访问的接口地址。")
    return url


def _request_json(
    url: str,
    headers: dict[str, str],
    opener: Callable[..., object],
    *,
    allow_remote_http: bool = False,
) -> dict:
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with opener(request, timeout=15) as response:
        final_url = getattr(response, "geturl", lambda: url)()
        if not _is_allowed_url(final_url, allow_remote_http):
            raise ValueError("音源接口重定向到了不允许的地址。")
        payload = response.read(MAX_CATALOG_RESPONSE + 1)
    if len(payload) > MAX_CATALOG_RESPONSE:
        raise ValueError("音源返回数据过大。")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("音源没有返回有效的 UTF-8 JSON。") from exc
    if not isinstance(value, dict):
        raise ValueError("音源响应顶层必须是 JSON 对象。")
    return value


def _duration(seconds: object) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return ""
    return f"{total // 60:02d}:{total % 60:02d}"


def _quality_details(qualities: list[str], extra: dict | None = None) -> tuple[list, dict]:
    types = []
    details = {}
    for quality in qualities:
        data = dict((extra or {}).get(quality, {}))
        types.append({"type": quality, **data})
        details[quality] = data
    return types, details


def _track_from_lx(info: dict, source: dict) -> dict:
    available = [
        item.get("type")
        for item in info.get("types", [])
        if isinstance(item, dict) and item.get("type") in source["qualities"]
    ]
    qualities = list(dict.fromkeys(available)) or list(source["qualities"])
    return {
        "id": str(info.get("songmid") or info.get("songId") or info.get("hash") or ""),
        "title": str(info.get("name", "")).strip(),
        "artist": str(info.get("singer", "")).strip(),
        "album": str(info.get("albumName", "")).strip(),
        "duration": str(info.get("interval", "")).strip(),
        "cover_url": str(info.get("img", "") or ""),
        "qualities": qualities,
        "music_info": info,
    }


def _lx_search_kw(source: dict, query: str, opener) -> list[dict]:
    params = {
        "client": "kt",
        "all": query,
        "pn": 0,
        "rn": 30,
        "uid": "794762570",
        "ver": "kwplayer_ar_9.2.2.1",
        "vipver": 1,
        "show_copyright_off": 1,
        "newver": 1,
        "ft": "music",
        "cluster": 0,
        "strategy": 2012,
        "encoding": "utf8",
        "rformat": "json",
        "vermerge": 1,
        "mobi": 1,
        "issubtitle": 1,
    }
    payload = _request_json(
        "http://search.kuwo.cn/r.s?" + urllib.parse.urlencode(params),
        {},
        opener,
        allow_remote_http=True,
    )
    tracks = []
    pattern = re.compile(r"level:(\w+),bitrate:(\d+),format:(\w+),size:([\w.]+)")
    bitrate_map = {"128": "128k", "320": "320k", "2000": "flac", "4000": "flac24bit"}
    for item in payload.get("abslist", [])[:50]:
        details: dict[str, dict] = {}
        for match in pattern.finditer(str(item.get("N_MINFO", ""))):
            quality = bitrate_map.get(match.group(2))
            if quality:
                details[quality] = {"size": match.group(4).upper()}
        qualities = [q for q in SUPPORTED_QUALITIES if q in details]
        types, quality_details = _quality_details(qualities, details)
        info = {
            "name": html.unescape(str(item.get("SONGNAME", ""))),
            "singer": html.unescape(str(item.get("ARTIST", ""))).replace("&", "、"),
            "source": "kw",
            "songmid": str(item.get("MUSICRID", "")).replace("MUSIC_", ""),
            "albumId": str(item.get("ALBUMID", "")),
            "albumName": html.unescape(str(item.get("ALBUM", ""))),
            "interval": _duration(item.get("DURATION")),
            "img": None,
            "lrc": None,
            "otherSource": None,
            "types": types,
            "_types": quality_details,
            "typeUrl": {},
        }
        if info["name"] and info["songmid"]:
            tracks.append(_track_from_lx(info, source))
    return tracks


def _lx_search_kg(source: dict, query: str, opener) -> list[dict]:
    params = {
        "keyword": query,
        "page": 1,
        "pagesize": 30,
        "userid": 0,
        "clientver": "",
        "platform": "WebFilter",
        "filter": 2,
        "iscorrection": 1,
        "privilege_filter": 0,
        "area_code": 1,
    }
    payload = _request_json(
        "https://songsearch.kugou.com/song_search_v2?" + urllib.parse.urlencode(params),
        {},
        opener,
    )
    items = payload.get("data", {}).get("lists", [])
    tracks = []
    seen = set()
    for original in items[:50]:
        for item in [original, *(original.get("Grp") or [])]:
            key = (item.get("Audioid"), item.get("FileHash"))
            if key in seen:
                continue
            seen.add(key)
            fields = (
                ("128k", "FileSize", "FileHash"),
                ("320k", "HQFileSize", "HQFileHash"),
                ("flac", "SQFileSize", "SQFileHash"),
                ("flac24bit", "ResFileSize", "ResFileHash"),
            )
            details = {
                quality: {"hash": str(item.get(hash_key, ""))}
                for quality, size_key, hash_key in fields
                if item.get(size_key)
            }
            types, quality_details = _quality_details(list(details), details)
            singers = item.get("Singers") or []
            singer = "、".join(
                str(value.get("name", "")) for value in singers if isinstance(value, dict)
            ) or str(item.get("SingerName", ""))
            info = {
                "name": html.unescape(str(item.get("SongName", ""))),
                "singer": html.unescape(singer),
                "albumName": html.unescape(str(item.get("AlbumName", ""))),
                "albumId": item.get("AlbumID"),
                "songmid": item.get("Audioid"),
                "source": "kg",
                "interval": _duration(item.get("Duration")),
                "_interval": item.get("Duration"),
                "hash": item.get("FileHash"),
                "img": None,
                "lrc": None,
                "otherSource": None,
                "types": types,
                "_types": quality_details,
                "typeUrl": {},
            }
            if info["name"] and info["songmid"]:
                tracks.append(_track_from_lx(info, source))
    return tracks


def _lx_search_tx(source: dict, query: str, opener) -> list[dict]:
    params = {"p": 1, "n": 30, "w": query, "format": "json"}
    payload = _request_json(
        "https://c.y.qq.com/soso/fcgi-bin/client_search_cp?"
        + urllib.parse.urlencode(params),
        {"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"},
        opener,
    )
    tracks = []
    for item in payload.get("data", {}).get("song", {}).get("list", [])[:50]:
        file_info = item.get("file") or {}
        details = {
            quality: {}
            for quality, key in (
                ("128k", "size_128mp3"),
                ("320k", "size_320mp3"),
                ("flac", "size_flac"),
                ("flac24bit", "size_hires"),
            )
            if file_info.get(key)
        }
        types, quality_details = _quality_details(list(details), details)
        singers = "、".join(
            str(singer.get("name", ""))
            for singer in item.get("singer", [])
            if isinstance(singer, dict)
        )
        album = item.get("album") or {}
        album_mid = album.get("mid") or item.get("albummid") or ""
        media_mid = file_info.get("media_mid") or item.get("strMediaMid") or ""
        info = {
            "name": item.get("songname") or item.get("title") or "",
            "singer": singers,
            "albumName": album.get("name") or item.get("albumname") or "",
            "albumId": album_mid,
            "source": "tx",
            "interval": _duration(item.get("interval")),
            "songId": item.get("songid") or item.get("id"),
            "albumMid": album_mid,
            "strMediaMid": media_mid,
            "songmid": item.get("songmid") or item.get("mid"),
            "img": (
                f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{album_mid}.jpg"
                if album_mid
                else ""
            ),
            "types": types,
            "_types": quality_details,
            "typeUrl": {},
        }
        if info["name"] and info["songmid"]:
            tracks.append(_track_from_lx(info, source))
    return tracks


def _lx_search_wy(source: dict, query: str, opener) -> list[dict]:
    params = {"s": query, "type": 1, "offset": 0, "total": "true", "limit": 30}
    payload = _request_json(
        "https://music.163.com/api/search/get/web?" + urllib.parse.urlencode(params),
        {"Referer": "https://music.163.com/", "User-Agent": "Mozilla/5.0"},
        opener,
    )
    tracks = []
    for item in payload.get("result", {}).get("songs", [])[:50]:
        qualities = ["128k"]
        if item.get("hMusic") or item.get("h"):
            qualities.append("320k")
        if item.get("sqMusic") or item.get("sq"):
            qualities.append("flac")
        types, quality_details = _quality_details(qualities)
        artists = item.get("artists") or item.get("ar") or []
        album = item.get("album") or item.get("al") or {}
        info = {
            "name": item.get("name", ""),
            "singer": "、".join(
                str(artist.get("name", ""))
                for artist in artists
                if isinstance(artist, dict)
            ),
            "albumName": album.get("name", ""),
            "albumId": album.get("id", ""),
            "source": "wy",
            "interval": _duration((item.get("duration") or item.get("dt") or 0) / 1000),
            "songmid": item.get("id"),
            "img": album.get("picUrl", ""),
            "lrc": None,
            "types": types,
            "_types": quality_details,
            "typeUrl": {},
        }
        if info["name"] and info["songmid"]:
            tracks.append(_track_from_lx(info, source))
    return tracks


def _lx_search_mg(source: dict, query: str, opener) -> list[dict]:
    timestamp = str(int(time.time() * 1000))
    device_id = "963B7AA0D21511ED807EE5846EC87D20"
    signature = hashlib.md5(
        (
            query
            + "6cdc72a439cef99a3418d2a78aa28c73"
            + "yyapp2d16148780a1dcc7408e06336b98cfd50"
            + device_id
            + timestamp
        ).encode()
    ).hexdigest()
    params = {
        "isCorrect": 0,
        "isCopyright": 1,
        "searchSwitch": json.dumps(
            {
                "song": 1,
                "album": 0,
                "singer": 0,
                "tagSong": 1,
                "mvSong": 0,
                "bestShow": 1,
                "songlist": 0,
                "lyricSong": 0,
            },
            separators=(",", ":"),
        ),
        "pageSize": 30,
        "text": query,
        "pageNo": 1,
        "sort": 0,
        "sid": "USS",
    }
    payload = _request_json(
        "https://jadeite.migu.cn/music_search/v3/search/searchAll?"
        + urllib.parse.urlencode(params),
        {
            "uiVersion": "A_music_3.6.1",
            "deviceId": device_id,
            "timestamp": timestamp,
            "sign": signature,
            "channel": "0146921",
            "User-Agent": "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36",
        },
        opener,
    )
    tracks = []
    groups = payload.get("songResultData", {}).get("resultList", [])
    for group in groups:
        for item in group if isinstance(group, list) else []:
            details = {}
            for value in item.get("audioFormats") or []:
                quality = {
                    "PQ": "128k",
                    "HQ": "320k",
                    "SQ": "flac",
                    "ZQ24": "flac24bit",
                }.get(value.get("formatType"))
                if quality:
                    details[quality] = {}
            types, quality_details = _quality_details(list(details), details)
            singer = "、".join(
                str(value.get("name", ""))
                for value in item.get("singerList") or []
                if isinstance(value, dict)
            )
            info = {
                "name": item.get("name", ""),
                "singer": singer,
                "albumName": item.get("album", ""),
                "albumId": item.get("albumId", ""),
                "songmid": item.get("songId"),
                "copyrightId": item.get("copyrightId"),
                "source": "mg",
                "interval": _duration(item.get("duration")),
                "img": item.get("img3") or item.get("img2") or item.get("img1"),
                "lrc": None,
                "lrcUrl": item.get("lrcUrl"),
                "mrcUrl": item.get("mrcurl"),
                "trcUrl": item.get("trcUrl"),
                "types": types,
                "_types": quality_details,
                "typeUrl": {},
            }
            if info["name"] and info["songmid"]:
                tracks.append(_track_from_lx(info, source))
    return tracks[:50]


_LX_SEARCHERS = {
    "kw": _lx_search_kw,
    "kg": _lx_search_kg,
    "tx": _lx_search_tx,
    "wy": _lx_search_wy,
    "mg": _lx_search_mg,
}


def search_source(
    source: dict,
    query: str,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> list[dict]:
    """Search a validated source and normalize its track list."""

    source = validate_source_config(source)
    query = query.strip()
    if not query:
        return []
    if source["type"] == "lx_js":
        searcher = _LX_SEARCHERS.get(source["source_key"])
        if searcher is None:
            raise ValueError("当前平台暂不支持歌曲搜索。")
        return searcher(source, query, opener)

    url = _endpoint(source, source["search_path"], query=query)
    payload = _request_json(url, source["headers"], opener)
    tracks = payload.get("tracks", [])
    if not isinstance(tracks, list):
        raise ValueError("音源搜索响应缺少 tracks 数组。")
    normalized: list[dict] = []
    for item in tracks[:100]:
        if not isinstance(item, dict):
            continue
        track_id = str(item.get("id", "")).strip()
        title = str(item.get("title", "")).strip()
        if not track_id or not title:
            continue
        item_qualities = item.get("qualities", source["qualities"])
        qualities = (
            [
                str(value)
                for value in item_qualities
                if str(value) in source["qualities"]
            ]
            if isinstance(item_qualities, list)
            else list(source["qualities"])
        )
        direct_urls = item.get("urls", {})
        if not isinstance(direct_urls, dict):
            direct_urls = {}
        normalized.append(
            {
                "id": track_id,
                "title": title,
                "artist": str(item.get("artist", "")).strip(),
                "album": str(item.get("album", "")).strip(),
                "duration": str(item.get("duration", "")).strip(),
                "cover_url": str(item.get("cover_url", "")).strip(),
                "qualities": qualities or list(source["qualities"]),
                "download_url": str(item.get("download_url", "")).strip(),
                "urls": {
                    str(key): str(value)
                    for key, value in direct_urls.items()
                    if isinstance(key, str) and isinstance(value, str)
                },
            }
        )
    return normalized


def resolve_download(
    source: dict,
    track: dict,
    quality: str,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[str, dict[str, str]]:
    """Resolve a selected track to a final audio URL and request headers."""

    source = validate_source_config(source)
    if quality not in source["qualities"]:
        raise ValueError("该音源不支持所选音质。")
    if source["type"] == "lx_js":
        path = Path(source["script_path"])
        if not path.exists():
            raise ValueError("JS 音源文件已丢失，请在设置中重新导入。")
        script = path.read_text(encoding="utf-8-sig")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        if source.get("script_sha256") and digest != source["script_sha256"]:
            raise ValueError("JS 音源文件已被修改，请重新导入后再使用。")
        music_info = track.get("music_info")
        if not isinstance(music_info, dict):
            raise ValueError("搜索结果缺少 JS 音源所需的歌曲信息。")
        try:
            value = _run_lx_worker(
                {
                    "action": "resolve",
                    "script": script,
                    "metadata": source.get("metadata", {}),
                    "source_key": source["source_key"],
                    "quality": quality,
                    "music_info": music_info,
                },
                timeout=45,
            )
        except ValueError as exc:
            # A number of LX sources return only ``failed`` or a numeric code
            # when a catalog result cannot be streamed.  Passing that raw
            # response to the UI looks like an application crash even though
            # the selected item is simply unavailable from this source.
            detail = str(exc).strip()
            if detail.casefold() in {"fail", "failed", "null", "undefined"} or (
                detail.isdigit() and len(detail) <= 8
            ):
                raise ValueError(
                    "当前音源没有提供这首歌的可播放地址。"
                    "可能受版权、VIP、地区限制或音源临时失效影响，"
                    "请换一条搜索结果或切换音源。"
                ) from exc
            raise
        url = str(value.get("url", "")).strip()
        if not _is_allowed_url(url, allow_remote_http=True):
            raise ValueError("JS 音源没有返回有效的歌曲地址。")
        return url, {}

    direct_url = str(track.get("urls", {}).get(quality, "")).strip()
    direct_url = direct_url or str(track.get("download_url", "")).strip()
    headers = dict(source["headers"])
    if direct_url:
        if not _is_allowed_url(direct_url):
            raise ValueError("音源返回的下载地址必须使用 HTTPS。")
        return direct_url, headers
    if not source["resolve_path"]:
        raise ValueError("音源没有提供下载地址，也没有配置解析路径。")
    url = _endpoint(
        source,
        source["resolve_path"],
        id=str(track.get("id", "")),
        quality=quality,
    )
    payload = _request_json(url, headers, opener)
    resolved = str(payload.get("url", "")).strip()
    if not _is_allowed_url(resolved):
        raise ValueError("音源解析结果不是允许的 HTTPS 下载地址。")
    extra_headers = payload.get("headers", {})
    if isinstance(extra_headers, dict):
        headers.update(
            {
                str(key): str(value)
                for key, value in extra_headers.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    return resolved, headers


def suggested_filename(track: dict, quality: str) -> str:
    artist = str(track.get("artist", "")).strip()
    title = str(track.get("title", "未命名音频")).strip()
    extension = ".flac" if quality.startswith("flac") else ".mp3"
    name = f"{artist} - {title}" if artist else title
    name = _INVALID_FILENAME.sub("_", name).strip(" .")[:160] or "未命名音频"
    return name + extension


def download_audio(
    url: str,
    headers: dict[str, str],
    requested_path: str | Path,
    progress: Callable[[int], None] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    *,
    allow_remote_http: bool = False,
) -> str:
    """Stream an authorized URL to a new local file without overwriting."""

    if not _is_allowed_url(url, allow_remote_http):
        raise ValueError("下载地址必须使用 HTTPS。")
    output_path = Path(unique_output_path(requested_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_suffix(output_path.suffix + ".part")
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with opener(request, timeout=30) as response, part_path.open("wb") as handle:
            final_url = getattr(response, "geturl", lambda: url)()
            if not _is_allowed_url(final_url, allow_remote_http):
                raise ValueError("下载地址重定向到了不允许的位置。")
            content_type = str(response.headers.get("Content-Type") or "").casefold()
            if content_type.startswith(("text/", "application/json")):
                raise ValueError("下载接口返回了网页或 JSON，而不是音频文件。")
            total = int(response.headers.get("Content-Length") or 0)
            copied = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                copied += len(chunk)
                if progress and total:
                    progress(min(99, int(copied * 100 / total)))
        shutil.move(str(part_path), str(output_path))
    finally:
        if part_path.exists():
            part_path.unlink()
    if progress:
        progress(100)
    return str(output_path)
