"""
本地 Whisper Provider

使用 openai-whisper 在本地运行语音识别。
需要安装: pip install openai-whisper
首次使用会自动下载模型。

优点: 离线可用，完全免费，数据不出本地
缺点: 需要 GPU 才能快速推理，纯 CPU 较慢
"""

import os
import logging
from typing import Optional

from .base import ASRProvider, Segment, TranscriptionResult

logger = logging.getLogger(__name__)


class LocalWhisperProvider(ASRProvider):
    """本地 OpenAI Whisper 实现"""
    
    # 内置模型大小
    AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large"]
    
    def __init__(self, model_name: str = "base"):
        self._model_name = model_name
        self._model = None
        self._device = None
    
    @property
    def name(self) -> str:
        return "local"
    
    @property
    def display_name(self) -> str:
        return f"本地 Whisper ({self._model_name})"
    
    def _get_model(self):
        if self._model is None:
            try: import whisper
            except ImportError: raise RuntimeError("openai-whisper not installed")
            try: import torch; self._device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError: self._device = "cpu"
            logger.info(f"Loading '{self._model_name}' (device:{self._device})...")
            from core.whisper_loader import load_hf_whisper
            self._model = load_hf_whisper(self._model_name)
            logger.info("Model loaded")
        
        return self._model
    
    def is_available(self) -> bool:
        """检查 whisper 是否已安装"""
        try:
            import whisper
            return True
        except ImportError:
            return False
    
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> TranscriptionResult:
        """本地转录音频"""
        model = self._get_model()
        
        # 转换语言代码 (Whisper 使用完整语言名)
        lang_map = {
            "zh": "Chinese",
            "en": "English",
            "ja": "Japanese",
            "ko": "Korean",
        }
        
        options = {}
        if language:
            options["language"] = lang_map.get(language, language)
        
        # 使用 fp16=false 兼容非 GPU 设备
        result = model.transcribe(
            audio_path,
            fp16=(self._device == "cuda"),
            verbose=False,
            **options,
        )
        
        # 解析结果
        segments = []
        detected_lang = result.get("language", "unknown")
        duration = result.get("duration", 0.0)
        
        for seg in result.get("segments", []):
            segments.append(Segment(
                start_time=seg.get("start", 0.0),
                end_time=seg.get("end", 0.0),
                text=seg.get("text", "").strip(),
                confidence=seg.get("avg_logprob", 0.0),
            ))
        
        return TranscriptionResult(
            segments=segments,
            language=detected_lang,
            duration=duration,
        )
