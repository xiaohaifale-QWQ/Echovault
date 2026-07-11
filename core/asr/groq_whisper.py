"""
Groq Whisper Provider

通过 Groq Cloud API 调用 Whisper Large v3 模型。
免费额度大，速度快，支持多语言。

文档: https://console.groq.com/docs/speech-text
"""

import os
import logging
from typing import Optional

from .base import ASRProvider, Segment, TranscriptionResult

logger = logging.getLogger(__name__)


class GroqWhisperProvider(ASRProvider):
    """Groq Cloud Whisper API 实现"""
    
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._client = None  # 懒加载
    
    @property
    def name(self) -> str:
        return "groq"
    
    @property
    def display_name(self) -> str:
        return "Groq Whisper (云端)"
    
    def _get_client(self):
        """懒加载 Groq 客户端"""
        if self._client is None:
            try:
                from groq import Groq
            except ImportError:
                raise RuntimeError(
                    "Groq SDK 未安装。请运行: pip install groq"
                )
            if not self._api_key:
                raise RuntimeError(
                    "Groq API Key 未设置。请设置环境变量 GROQ_API_KEY，"
                    "或在设置面板中配置。\n"
                    "免费获取: https://console.groq.com/keys"
                )
            self._client = Groq(api_key=self._api_key)
        return self._client
    
    def is_available(self) -> bool:
        """检查 API Key 是否已配置"""
        return bool(self._api_key)
    
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> TranscriptionResult:
        """
        通过 Groq API 转录音频
        
        Groq 支持的格式: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm
        文件大小限制: 25 MB
        """
        client = self._get_client()
        
        with open(audio_path, "rb") as f:
            # Groq API 参数
            kwargs = {
                "file": (os.path.basename(audio_path), f),
                "model": "whisper-large-v3",
                "response_format": "verbose_json",  # 带时间戳的详细结果
            }
            if language:
                kwargs["language"] = language
            
            response = client.audio.transcriptions.create(**kwargs)
        
        # 解析响应
        segments = []
        detected_lang = getattr(response, "language", "unknown")
        duration = getattr(response, "duration", 0.0)
        
        raw_segments = getattr(response, "segments", [])
        for seg in raw_segments:
            segments.append(Segment(
                start_time=seg.get("start", 0.0),
                end_time=seg.get("end", 0.0),
                text=seg.get("text", "").strip(),
                confidence=seg.get("avg_logprob", 0.0),  # Groq 返回的是 logprob
            ))
        
        return TranscriptionResult(
            segments=segments,
            language=detected_lang,
            duration=duration,
        )
