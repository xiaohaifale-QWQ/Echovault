"""
LRC 歌词生成器

将 ASR 识别结果（Segment 列表）转换为 LRC 格式歌词文件。

后处理包括：
- 合并过短的相邻句（间隔 < 1.5s 的合并为一行）
- 删除重复连续句
- 智能分行（按语义停顿拆分过长的行）
"""

import os
import re
from pathlib import Path
from typing import List, Optional

from .asr.base import Segment, TranscriptionResult
from .lrc_parser import LRCFile, LyricLine, format_timestamp


# 后处理参数
MIN_GAP_MERGE = 1.5       # 小于此间隔（秒）的相邻句合并
MAX_LINE_CHARS = 40       # 单行最大字符数（超过则拆分）
MAX_LINE_DURATION = 8.0   # 单行最大时长（秒）

# 常见中文歌词同音字修正（可扩展）
_COMMON_CORRECTIONS = {
    # 后续可添加更多纠错对
}


def _merge_short_segments(segments: List[Segment]) -> List[Segment]:
    """
    合并间隔过短的相邻句
    
    如果 A.end 和 B.start 之间的间隔 < MIN_GAP_MERGE，合并 A 和 B
    """
    if not segments:
        return []
    
    merged = []
    current = segments[0]
    
    for next_seg in segments[1:]:
        gap = next_seg.start_time - current.end_time
        if gap < MIN_GAP_MERGE:
            # 合并：延长时间，拼接文本
            current.end_time = next_seg.end_time
            current.text = current.text.rstrip() + " " + next_seg.text.lstrip()
        else:
            merged.append(current)
            current = next_seg
    
    merged.append(current)
    return merged


def _remove_duplicates(segments: List[Segment]) -> List[Segment]:
    """删除重复的连续句"""
    if not segments:
        return []
    
    result = [segments[0]]
    for seg in segments[1:]:
        if seg.text.strip() != result[-1].text.strip():
            result.append(seg)
    return result


def _split_long_lines(segments: List[Segment]) -> List[Segment]:
    """
    拆分过长或持续时间过久的歌词行
    按自然断句（标点符号）拆分
    """
    result = []
    for seg in segments:
        text = seg.text.strip()
        duration = seg.end_time - seg.start_time
        
        if len(text) <= MAX_LINE_CHARS and duration <= MAX_LINE_DURATION:
            result.append(seg)
            continue
        
        # 尝试按标点拆分
        parts = re.split(r'[，,。！!？?；;、\s]+', text)
        parts = [p.strip() for p in parts if p.strip()]
        
        if len(parts) <= 1:
            result.append(seg)
            continue
        
        # 按时间比例分配
        total_chars = sum(len(p) for p in parts)
        current_time = seg.start_time
        
        for part in parts:
            if not part:
                continue
            part_duration = (len(part) / total_chars) * duration if total_chars > 0 else duration / len(parts)
            result.append(Segment(
                start_time=current_time,
                end_time=current_time + part_duration,
                text=part,
                confidence=seg.confidence,
            ))
            current_time += part_duration
    
    return result


def _correct_common_errors(text: str, language: str) -> str:
    """
    常见识别错误修正
    
    中文：同音字替换
    英文：常见歌词拼写修正
    """
    if language.startswith("zh"):
        for wrong, correct in _COMMON_CORRECTIONS.items():
            text = text.replace(wrong, correct)
        # 繁体转简体
        try:
            from opencc import OpenCC
            cc = OpenCC('t2s')
            text = cc.convert(text)
        except ImportError:
            pass
    return text


def segments_to_lrc(
    result: TranscriptionResult,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    post_process: bool = True,
) -> LRCFile:
    """
    将识别结果转换为 LRC 文件对象
    
    Args:
        result: ASR 识别结果
        title: 歌曲标题
        artist: 歌手
        album: 专辑
        post_process: 是否启用后处理（合并短句、去重、分行）
    
    Returns:
        LRCFile: LRC 对象
    """
    segments = list(result.segments)
    
    if post_process and segments:
        # 1. 文本纠错
        for seg in segments:
            seg.text = _correct_common_errors(seg.text, result.language)
        
        # 2. 删除重复句
        segments = _remove_duplicates(segments)
        
        # 3. 合并过短的相邻句
        segments = _merge_short_segments(segments)
        
        # 4. 拆分过长的行
        segments = _split_long_lines(segments)
    
    lrc = LRCFile()
    lrc.title = title
    lrc.artist = artist
    lrc.album = album
    lrc.by = "MusicSync"
    
    for seg in segments:
        if seg.text.strip():
            lrc.lines.append(LyricLine(seg.start_time, seg.text))
    
    return lrc


def save_lrc(
    lrc: LRCFile,
    audio_path: str,
    output_dir: Optional[str] = None,
    overwrite: bool = False,
) -> str:
    """
    保存 LRC 文件
    
    Args:
        lrc: LRC 对象
        audio_path: 对应的音频文件路径（用于生成同名 LRC）
        output_dir: 输出目录，None = 与音频同目录
        overwrite: 是否覆盖已有 LRC
    
    Returns:
        str: 保存的 LRC 文件路径
    """
    audio_path = Path(audio_path)
    lrc_name = audio_path.stem + ".lrc"
    
    if output_dir:
        lrc_dir = Path(output_dir)
    else:
        lrc_dir = audio_path.parent
    
    lrc_dir.mkdir(parents=True, exist_ok=True)
    lrc_path = lrc_dir / lrc_name
    
    if lrc_path.exists() and not overwrite:
        raise FileExistsError(f"LRC 文件已存在: {lrc_path}")
    
    content = lrc.to_string()
    with open(lrc_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return str(lrc_path)


def transcribe_and_save_lrc(
    audio_path: str,
    router,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    language: Optional[str] = None,
    output_dir: Optional[str] = None,
    overwrite: bool = False,
    progress_callback=None,
) -> str:
    """
    一站式：音频 → 识别 → 后处理 → 保存 LRC
    
    Args:
        audio_path: 音频文件路径
        router: ASRRouter 实例
        title: 歌曲标题
        artist: 歌手
        language: 语言代码
        output_dir: LRC 输出目录
        overwrite: 是否覆盖已有文件
        progress_callback: 进度回调 callable(stage: str)
    
    Returns:
        str: 保存的 LRC 文件路径
    """
    from .audio_utils import convert_to_whisper_format, cleanup_temp_files
    
    song_name = os.path.basename(audio_path)
    
    # 1. 转换音频格式
    if progress_callback:
        progress_callback(f"🎵 转换音频... {song_name}")
    wav_path = convert_to_whisper_format(audio_path)
    
    try:
        # 2. ASR 识别
        if progress_callback:
            progress_callback(f"🎤 语音识别中... {song_name}")
        result = router.transcribe(wav_path, language=language)
        
        if result.is_empty:
            raise RuntimeError("未能识别出任何歌词内容")
        
        # 3. 转换为 LRC + 后处理
        if progress_callback:
            progress_callback(f"✍️ 后处理中... {song_name}")
        lrc = segments_to_lrc(result, title=title, artist=artist)
        
        # 4. 保存
        lrc_path = save_lrc(lrc, audio_path, output_dir=output_dir, overwrite=overwrite)
        
        return lrc_path
    
    finally:
        # 5. 清理临时文件
        cleanup_temp_files([wav_path])
