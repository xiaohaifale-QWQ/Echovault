"""
音频元数据读写模块

基于 mutagen 库，支持 MP3/FLAC/MP4/M4A/OGG 等格式的标签读写。
"""

from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, TPE2, TRCK, USLT
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis


# 支持的格式 → mutagen 类映射
_FORMAT_MAP = {
    ".mp3": MP3,
    ".flac": FLAC,
    ".m4a": MP4,
    ".mp4": MP4,
    ".ogg": OggVorbis,
    ".opus": OggOpus,
}


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
    
    if ext == ".mp3":
        tags = audio.tags if hasattr(audio, "tags") and audio.tags else {}
        result["title"] = str(tags.get("TIT2", ""))
        result["artist"] = str(tags.get("TPE1", ""))
        result["album"] = str(tags.get("TALB", ""))
        result["year"] = str(tags.get("TYER", ""))
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
