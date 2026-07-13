"""
音频工具模块

封装 ffmpeg/pydub 操作：
- 格式转换（任意格式 → 16kHz mono WAV，Whisper 输入格式）
- 音频信息提取（时长、采样率等）
- 支持的音频格式检测
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from pydub import AudioSegment

# 支持的音频格式
SUPPORTED_FORMATS = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".ape", ".wv"}

# Whisper 推荐输入格式
WHISPER_FORMAT = "wav"
WHISPER_SAMPLE_RATE = 16000
WHISPER_CHANNELS = 1  # mono


def is_supported(file_path: str) -> bool:
    """检查文件是否为支持的音频格式"""
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_FORMATS


def get_audio_info(file_path: str) -> dict:
    """
    获取音频文件信息（时长、采样率、声道数等）
    
    Returns:
        dict: {"duration": float, "sample_rate": int, "channels": int, "format": str}
    """
    audio = AudioSegment.from_file(file_path)
    return {
        "duration": len(audio) / 1000.0,          # 毫秒 → 秒
        "sample_rate": audio.frame_rate,
        "channels": audio.channels,
        "sample_width": audio.sample_width,
        "format": Path(file_path).suffix.lower().lstrip("."),
    }


def convert_to_whisper_format(
    file_path: str,
    output_path: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> str:
    """
    将音频文件转换为 Whisper 兼容格式 (16kHz mono WAV)
    
    Args:
        file_path: 源音频文件路径
        output_path: 输出路径，None = 自动生成临时文件
        start_time: 裁剪开始时间（秒），None = 从头
        end_time: 裁剪结束时间（秒），None = 到尾
    
    Returns:
        str: 转换后的 WAV 文件路径
    """
    args = ["ffmpeg", "-y", "-i", file_path]
    
    # 裁剪
    if start_time is not None:
        args.extend(["-ss", str(start_time)])
    if end_time is not None:
        args.extend(["-to", str(end_time)])
    
    # 转码参数
    args.extend([
        "-ar", str(WHISPER_SAMPLE_RATE),  # 采样率 16kHz
        "-ac", str(WHISPER_CHANNELS),      # 单声道
        "-sample_fmt", "s16",              # 16-bit PCM
    ])
    
    created_temp = output_path is None
    if output_path:
        args.append(output_path)
    else:
        # 使用唯一临时文件名，避免同名歌曲或并发任务互相覆盖。
        fd, output_path = tempfile.mkstemp(prefix="echovault_", suffix=".wav")
        os.close(fd)
        args.append(output_path)
    
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        if created_temp and os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError(
            "未找到 ffmpeg。请先安装 ffmpeg 并确保 ffmpeg 命令已加入 PATH。"
        ) from e
    except subprocess.CalledProcessError as e:
        if created_temp and os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError(f"音频转换失败: {e.stderr}") from e
    
    return output_path


def split_audio(file_path: str, max_duration: float = 600.0) -> list[str]:
    """
    将长音频切分为多个片段（Whisper 单次最长处理约 30 秒会自动切分，
    但超长文件（> 10 分钟）可能 OOM，这里提前切分）
    
    Args:
        file_path: 音频文件路径
        max_duration: 每段最大时长（秒），默认 600 秒 = 10 分钟
    
    Returns:
        list[str]: 切分后的临时文件路径列表
    """
    info = get_audio_info(file_path)
    duration = info["duration"]
    
    if duration <= max_duration:
        # 不需要切分，直接转换
        return [convert_to_whisper_format(file_path)]
    
    chunks = []
    try:
        for start in range(0, int(duration), int(max_duration)):
            end = min(start + max_duration, duration)
            chunk_path = convert_to_whisper_format(file_path, start_time=start, end_time=end)
            chunks.append(chunk_path)
    except Exception:
        cleanup_temp_files(chunks)
        raise
    
    return chunks


def cleanup_temp_files(file_paths: list[str]):
    """清理临时文件"""
    for path in file_paths:
        try:
            if os.path.exists(path) and tempfile.gettempdir() in path:
                os.remove(path)
        except OSError:
            pass
