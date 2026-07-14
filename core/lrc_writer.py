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
from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from opencc import OpenCC

from .asr.base import Segment, TranscriptionResult
from .lrc_parser import LRCFile, LyricLine

# 后处理参数
MIN_GAP_MERGE = 1.5  # 小于此间隔（秒）的相邻句合并
MAX_LINE_CHARS = 40  # 单行最大字符数（超过则拆分）
MAX_LINE_DURATION = 8.0  # 单行最大时长（秒）
RECOGNITION_CHUNK_DURATION = 15.0  # 真实进度更新粒度（秒）

# 常见中文歌词同音字修正（可扩展）
_COMMON_CORRECTIONS = {
    # 后续可添加更多纠错对
}

_T2S_CONVERTER = OpenCC("t2s")
_CHINESE_LANGUAGE_NAMES = {
    "chinese",
    "mandarin",
    "cmn",
    "zho",
    "chi",
    "中文",
    "汉语",
    "漢語",
    "普通话",
    "普通話",
}

# Whisper 在纯前奏或静音段偶尔会把训练语料中的制作署名误识别为歌词，
# 常见形式为“作曲”后紧跟一个人名。只处理识别结果最开头的连续署名，
# 避免误删歌曲正文中正常出现的词语。
_LEADING_CREDIT_LABELS = frozenset(
    {"作词", "作曲", "编曲", "填词", "词曲", "演唱", "歌手", "制作人", "制作"}
)
_LEADING_CREDIT_LABEL_RE = re.compile(
    r"^(?:作词|作曲|编曲|填词|词曲|演唱|歌手|制作人|制作)(?:\s*[:：]?\s*.+)?$"
)
_LEADING_CREDIT_VALUE_RE = re.compile(r"^[\w\u4e00-\u9fff·・'’\- ]{1,40}$")


def _is_chinese_language(language: Optional[str]) -> bool:
    if not language:
        return False
    normalized = language.strip().lower().replace("_", "-")
    return (
        normalized == "zh" or normalized.startswith("zh-") or normalized in _CHINESE_LANGUAGE_NAMES
    )


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
        parts = re.split(r"[，,。！!？?；;、\s]+", text)
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
            part_duration = (
                (len(part) / total_chars) * duration if total_chars > 0 else duration / len(parts)
            )
            result.append(
                Segment(
                    start_time=current_time,
                    end_time=current_time + part_duration,
                    text=part,
                    confidence=seg.confidence,
                )
            )
            current_time += part_duration

    return result


def _correct_common_errors(text: str, language: Optional[str]) -> str:
    """
    常见识别错误修正

    中文：同音字替换
    英文：常见歌词拼写修正
    """
    if _is_chinese_language(language):
        for wrong, correct in _COMMON_CORRECTIONS.items():
            text = text.replace(wrong, correct)
        text = _T2S_CONVERTER.convert(text)
    return text


def _remove_leading_credits(segments: List[Segment]) -> List[Segment]:
    """移除 ASR 在开头幻听出的制作署名，不触碰后续歌词。"""
    index = 0
    expects_credit_value = False

    while index < len(segments):
        text = segments[index].text.strip()
        if _LEADING_CREDIT_LABEL_RE.fullmatch(text):
            # 只有“作曲”这种孤立标签才会吃掉紧随的姓名；“作曲：某人”
            # 已经是完整署名，下一句必须作为正常歌词保留。
            expects_credit_value = text.rstrip(" ：:") in _LEADING_CREDIT_LABELS
            index += 1
            continue

        # 独立的“作曲”之后，Whisper 常将署名拆成下一条时间轴；只在
        # 已移除开头标签且该条看起来像简短姓名时一并删除。
        if expects_credit_value and _LEADING_CREDIT_VALUE_RE.fullmatch(text):
            index += 1
            expects_credit_value = False
            continue
        break

    return segments[index:]


def segments_to_lrc(
    result: TranscriptionResult,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    post_process: bool = True,
    language_hint: Optional[str] = None,
) -> LRCFile:
    """
    将识别结果转换为 LRC 文件对象

    Args:
        result: ASR 识别结果
        title: 歌曲标题
        artist: 歌手
        album: 专辑
        post_process: 是否启用结构后处理（合并短句、去重、分行）
        language_hint: 用户指定的语言；用于确保中文结果转换为简体

    Returns:
        LRCFile: LRC 对象
    """
    # Copy segments so output normalization never mutates the provider result.
    segments = [replace(segment) for segment in result.segments]
    normalization_language = language_hint or result.language

    # Chinese text normalization is an output guarantee, independent of optional
    # structural post-processing.
    for segment in segments:
        segment.text = _correct_common_errors(segment.text, normalization_language)

    segments = _remove_leading_credits(segments)

    if post_process and segments:
        # 1. 删除重复句
        segments = _remove_duplicates(segments)

        # 2. 合并过短的相邻句
        segments = _merge_short_segments(segments)

        # 3. 拆分过长的行
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
    temp_path = lrc_path.with_suffix(lrc_path.suffix + ".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(lrc_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

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
        progress_callback: 进度回调 callable(RecognitionProgress)

    Returns:
        str: 保存的 LRC 文件路径
    """
    from .audio_utils import cleanup_temp_files, split_audio
    from .recognition_progress import RecognitionProgress

    song_name = os.path.basename(audio_path)

    # 1. 转换并切分音频。每段约 15 秒，每完成一段都意味着模型完成了
    # 一次真实推理，因此 UI 能显示真实可观察的识别进度而不是计时器动画。
    if progress_callback:
        progress_callback(RecognitionProgress(0, "prepare", f"正在转换音频… {song_name}"))
    wav_paths = split_audio(audio_path, max_duration=RECOGNITION_CHUNK_DURATION)

    try:
        if progress_callback:
            progress_callback(
                RecognitionProgress(
                    5,
                    "prepare",
                    f"音频已切为 {len(wav_paths)} 段，准备识别… {song_name}",
                    0,
                    len(wav_paths),
                )
            )
        # 2. ASR 识别
        combined_segments = []
        detected_language = "unknown"
        total_duration = 0.0
        for index, wav_path in enumerate(wav_paths):
            if progress_callback:
                progress_callback(
                    RecognitionProgress(
                        5 + int(85 * index / len(wav_paths)),
                        "transcribe",
                        (
                            f"正在识别第 {index + 1}/{len(wav_paths)} 段"
                            f"（约 {RECOGNITION_CHUNK_DURATION:.0f} 秒）… {song_name}"
                        ),
                        index + 1,
                        len(wav_paths),
                    )
                )
            chunk_result = router.transcribe(wav_path, language=language)
            offset = index * RECOGNITION_CHUNK_DURATION
            for segment in chunk_result.segments:
                combined_segments.append(
                    Segment(
                        start_time=segment.start_time + offset,
                        end_time=segment.end_time + offset,
                        text=segment.text,
                        confidence=segment.confidence,
                    )
                )
            if detected_language == "unknown":
                detected_language = chunk_result.language
            total_duration = max(total_duration, offset + chunk_result.duration)
            if progress_callback:
                progress_callback(
                    RecognitionProgress(
                        5 + int(85 * (index + 1) / len(wav_paths)),
                        "transcribe",
                        f"已完成第 {index + 1}/{len(wav_paths)} 段… {song_name}",
                        index + 1,
                        len(wav_paths),
                    )
                )

        result = TranscriptionResult(
            segments=combined_segments,
            language=detected_language,
            duration=total_duration,
        )

        if result.is_empty:
            raise RuntimeError("未能识别出任何歌词内容")

        # 3. 转换为 LRC + 后处理
        if progress_callback:
            progress_callback(RecognitionProgress(92, "postprocess", f"正在整理歌词… {song_name}"))
        lrc = segments_to_lrc(
            result,
            title=title,
            artist=artist,
            language_hint=language,
        )

        # 4. 保存
        if progress_callback:
            progress_callback(RecognitionProgress(96, "save", f"正在写入 LRC… {song_name}"))
        lrc_path = save_lrc(lrc, audio_path, output_dir=output_dir, overwrite=overwrite)
        if progress_callback:
            progress_callback(RecognitionProgress(100, "done", f"识别完成… {song_name}"))

        return lrc_path

    finally:
        # 5. 清理临时文件
        cleanup_temp_files(wav_paths)
