"""
音频元数据读写模块

基于 mutagen 库，支持 MP3/FLAC/MP4/M4A/OGG 等格式的标签读写。
"""

import base64
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TDRC,
    TIT2,
    TPE1,
    TRCK,
    USLT,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from core.cover_art import image_mime_type

# 支持的格式 → mutagen 类映射
_FORMAT_MAP = {
    ".mp3": MP3,
    ".flac": FLAC,
    ".m4a": MP4,
    ".mp4": MP4,
    ".ogg": OggVorbis,
    ".opus": OggOpus,
    ".wav": WAVE,
}

COVER_EDITABLE_FORMATS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".wav"}


def _get_mutagen_file(file_path: str):
    """获取 mutagen 文件对象"""
    ext = Path(file_path).suffix.lower()

    if ext == ".mp3":
        # MP3 用 ID3 处理
        return MP3(file_path, ID3=ID3)

    cls = _FORMAT_MAP.get(ext)
    if cls is None:
        return MutagenFile(file_path)

    return cls(file_path)


def read_tags(file_path: str) -> dict:
    """
    读取音频文件的元数据标签

    Returns:
        dict: {"title", "artist", "album", "year", "track", "lyrics", "cover_mime"}
    """
    audio = _get_mutagen_file(file_path)
    if audio is None:
        return {}

    ext = Path(file_path).suffix.lower()

    result = {}

    if ext in {".mp3", ".wav"}:
        tags = audio.tags if hasattr(audio, "tags") and audio.tags else {}
        result["title"] = str(tags.get("TIT2", ""))
        result["artist"] = str(tags.get("TPE1", ""))
        result["album"] = str(tags.get("TALB", ""))
        result["year"] = str(tags.get("TDRC", tags.get("TYER", "")))
        result["track"] = str(tags.get("TRCK", ""))
        # USLT = Unsynchronised lyrics
        uslt = tags.getall("USLT")
        result["lyrics"] = str(uslt[0]) if uslt else ""

    elif ext == ".flac":
        result["title"] = str(audio.get("title", [""])[0]) if audio.get("title") else ""
        result["artist"] = str(audio.get("artist", [""])[0]) if audio.get("artist") else ""
        result["album"] = str(audio.get("album", [""])[0]) if audio.get("album") else ""
        result["year"] = str(audio.get("date", [""])[0]) if audio.get("date") else ""
        result["track"] = str(audio.get("tracknumber", [""])[0]) if audio.get("tracknumber") else ""
        result["lyrics"] = str(audio.get("lyrics", [""])[0]) if audio.get("lyrics") else ""

    elif ext in (".m4a", ".mp4"):
        result["title"] = str(audio.get("\xa9nam", [""])[0]) if audio.get("\xa9nam") else ""
        result["artist"] = str(audio.get("\xa9ART", [""])[0]) if audio.get("\xa9ART") else ""
        result["album"] = str(audio.get("\xa9alb", [""])[0]) if audio.get("\xa9alb") else ""
        result["year"] = str(audio.get("\xa9day", [""])[0]) if audio.get("\xa9day") else ""
        result["track"] = str(audio.get("trkn", [(0, 0)])[0][0]) if audio.get("trkn") else ""
        result["lyrics"] = str(audio.get("\xa9lyr", [""])[0]) if audio.get("\xa9lyr") else ""

    elif ext in (".ogg", ".opus"):
        result["title"] = str(audio.get("title", [""])[0]) if audio.get("title") else ""
        result["artist"] = str(audio.get("artist", [""])[0]) if audio.get("artist") else ""
        result["album"] = str(audio.get("album", [""])[0]) if audio.get("album") else ""
        result["year"] = str(audio.get("date", [""])[0]) if audio.get("date") else ""
        result["track"] = str(audio.get("tracknumber", [""])[0]) if audio.get("tracknumber") else ""
        result["lyrics"] = str(audio.get("lyrics", [""])[0]) if audio.get("lyrics") else ""

    return result


def write_lyrics_tag(file_path: str, lyrics: str):
    """
    将歌词写入音频文件的标签中（内嵌歌词）

    Args:
        file_path: 音频文件路径
        lyrics: 歌词文本
    """
    ext = Path(file_path).suffix.lower()
    audio = _get_mutagen_file(file_path)
    if audio is None:
        return

    if ext == ".mp3":
        if audio.tags is None:
            audio.add_tags()
        # 移除旧的 USLT
        audio.tags.delall("USLT")
        audio.tags.add(USLT(
            encoding=3,  # UTF-8
            lang="eng" if lyrics.isascii() else "zho",
            desc="Lyrics",
            text=lyrics,
        ))

    elif ext == ".flac":
        audio["lyrics"] = lyrics

    elif ext in (".m4a", ".mp4"):
        audio["\xa9lyr"] = lyrics

    elif ext in (".ogg", ".opus"):
        audio["lyrics"] = lyrics

    audio.save()


def write_tags(file_path: str, values: dict) -> None:
    """Update common music tags without re-encoding the audio stream."""
    audio = _get_mutagen_file(file_path)
    if audio is None:
        raise ValueError("无法读取当前音频文件的标签。")
    ext = Path(file_path).suffix.lower()
    fields = {
        key: str(values.get(key, "")).strip()
        for key in ("title", "artist", "album", "year", "track")
    }

    if ext in {".mp3", ".wav"}:
        if audio.tags is None:
            audio.add_tags()
        frames = {
            "title": ("TIT2", TIT2),
            "artist": ("TPE1", TPE1),
            "album": ("TALB", TALB),
            "year": ("TDRC", TDRC),
            "track": ("TRCK", TRCK),
        }
        for key, (frame_id, frame_class) in frames.items():
            audio.tags.delall(frame_id)
            if fields[key]:
                audio.tags.add(frame_class(encoding=3, text=fields[key]))
    elif ext in {".m4a", ".mp4"}:
        mapping = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album": "\xa9alb",
            "year": "\xa9day",
        }
        for key, tag in mapping.items():
            if fields[key]:
                audio[tag] = [fields[key]]
            elif tag in audio:
                del audio[tag]
        if fields["track"]:
            try:
                track_number = int(fields["track"].split("/", 1)[0])
            except ValueError:
                track_number = 0
            audio["trkn"] = [(track_number, 0)]
        elif "trkn" in audio:
            del audio["trkn"]
    else:
        mapping = {
            "title": "title",
            "artist": "artist",
            "album": "album",
            "year": "date",
            "track": "tracknumber",
        }
        for key, tag in mapping.items():
            if fields[key]:
                audio[tag] = fields[key]
            elif tag in audio:
                del audio[tag]
    audio.save()


def read_cover_art(file_path: str) -> tuple[bytes, str] | None:
    """Read the first embedded front cover from a supported audio file."""
    audio = _get_mutagen_file(file_path)
    if audio is None:
        return None
    ext = Path(file_path).suffix.lower()

    if ext in {".mp3", ".wav"}:
        tags = getattr(audio, "tags", None)
        pictures = tags.getall("APIC") if tags is not None else []
        if pictures:
            data = bytes(pictures[0].data)
            return data, image_mime_type(data, pictures[0].mime)
        return None

    if ext == ".flac":
        pictures = getattr(audio, "pictures", [])
        if pictures:
            picture = next(
                (item for item in pictures if getattr(item, "type", 0) == 3),
                pictures[0],
            )
            data = bytes(picture.data)
            return data, image_mime_type(data, picture.mime)
        return None

    if ext in {".m4a", ".mp4"}:
        covers = audio.get("covr", [])
        if covers:
            data = bytes(covers[0])
            return data, image_mime_type(data)
        return None

    if ext in {".ogg", ".opus"}:
        encoded = audio.get("metadata_block_picture", [])
        if encoded:
            try:
                picture = Picture(base64.b64decode(encoded[0]))
            except (TypeError, ValueError):
                return None
            data = bytes(picture.data)
            return data, image_mime_type(data, picture.mime)
        legacy = audio.get("coverart", [])
        if legacy:
            try:
                data = base64.b64decode(legacy[0])
            except (TypeError, ValueError):
                return None
            mime_values = audio.get("coverartmime", [])
            fallback = str(mime_values[0]) if mime_values else ""
            return data, image_mime_type(data, fallback)
    return None


def write_cover_art(file_path: str, image_data: bytes, mime_type: str) -> None:
    """Replace the embedded front cover without changing the audio stream."""
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext not in COVER_EDITABLE_FORMATS:
        raise ValueError(
            f"{ext or '当前'} 格式暂不支持写入封面；支持 MP3、FLAC、M4A、"
            "OGG、Opus 和 WAV。"
        )
    detected_mime = image_mime_type(image_data, mime_type)
    if detected_mime not in {"image/jpeg", "image/png"}:
        raise ValueError("封面必须是 JPEG 或 PNG 图片。")
    audio = _get_mutagen_file(str(path))
    if audio is None:
        raise ValueError("无法读取当前音频文件的标签。")

    if ext in {".mp3", ".wav"}:
        if audio.tags is None:
            audio.add_tags()
        audio.tags.delall("APIC")
        audio.tags.add(
            APIC(
                encoding=3,
                mime=detected_mime,
                type=3,
                desc="Cover",
                data=image_data,
            )
        )
    elif ext == ".flac":
        audio.clear_pictures()
        picture = Picture()
        picture.type = 3
        picture.mime = detected_mime
        picture.desc = "Cover"
        picture.data = image_data
        audio.add_picture(picture)
    elif ext in {".m4a", ".mp4"}:
        image_format = (
            MP4Cover.FORMAT_PNG
            if detected_mime == "image/png"
            else MP4Cover.FORMAT_JPEG
        )
        audio["covr"] = [MP4Cover(image_data, imageformat=image_format)]
    else:
        picture = Picture()
        picture.type = 3
        picture.mime = detected_mime
        picture.desc = "Cover"
        picture.data = image_data
        audio["metadata_block_picture"] = [
            base64.b64encode(picture.write()).decode("ascii")
        ]
        if "coverart" in audio:
            del audio["coverart"]
        if "coverartmime" in audio:
            del audio["coverartmime"]

    audio.save()

    from core.transfer_session import register_artifact

    register_artifact(path, path, "cover_art")
