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
from collections.abc import Callable, Sequence
from typing import Optional

from .base import ASRProvider, Segment, TranscriptionResult
from .worker_client import WorkerClient, WorkerClientError

logger = logging.getLogger(__name__)


class LocalWhisperProvider(ASRProvider):
    """本地 OpenAI Whisper 实现"""
    
    # 内置模型大小
    AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large"]
    
    def __init__(
        self,
        model_name: str = "base",
        use_gpu: bool = False,
        *,
        worker_command: Sequence[str] | None = None,
        worker_client_factory: Callable[[Sequence[str]], WorkerClient] = WorkerClient,
    ):
        self._model_name = model_name
        self._model = None
        self._device = None
        self._use_gpu = use_gpu
        self._worker_command = list(worker_command) if worker_command else None
        self._worker_client_factory = worker_client_factory
        self._worker_client: WorkerClient | None = None
    
    @property
    def name(self) -> str:
        return "local"
    
    @property
    def display_name(self) -> str:
        if self._device == "cuda":
            dev = "GPU"
        elif self._device == "cpu":
            dev = "CPU"
        elif self._worker_command:
            dev = "GPU 运行时"
        else:
            dev = "检测中"
        return f"本地 Whisper ({self._model_name}, {dev})"
    
    def _get_model(self):
        if self._model is None:
            try: import whisper
            except ImportError: raise RuntimeError("openai-whisper not installed")
            try:
                import torch
            except ImportError:
                self._device = "cpu"
            else:
                cuda_available = torch.cuda.is_available()
                self._device = "cuda" if self._use_gpu and cuda_available else "cpu"
                if self._use_gpu and not cuda_available:
                    logger.warning("GPU 已启用，但当前 PyTorch 不支持 CUDA；回退到 CPU")
            logger.info(f"Loading '{self._model_name}' (device:{self._device})...")
            from core.whisper_loader import load_hf_whisper
            self._model = load_hf_whisper(self._model_name, device=self._device)
            logger.info("Model loaded")
        
        return self._model

    def _get_worker_client(self) -> WorkerClient:
        if not self._worker_command:
            raise RuntimeError("未配置外置 ASR Worker")
        if self._worker_client is None:
            self._worker_client = self._worker_client_factory(self._worker_command)
        return self._worker_client
    
    def is_available(self) -> bool:
        """检查 whisper 是否已安装"""
        if self._worker_command:
            try:
                report = self._get_worker_client().request("doctor", timeout=10)
                self._device = str(report.get("device", "cpu"))
                return bool(report.get("torch_installed"))
            except WorkerClientError:
                return False
        try:
            import whisper
            return True
        except ImportError:
            return False
    
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> TranscriptionResult:
        """本地转录音频"""
        if self._worker_command:
            try:
                payload = self._get_worker_client().request(
                    "transcribe",
                    audio=audio_path,
                    model=self._model_name,
                    language=language,
                    cache_dir=os.path.join(os.path.expanduser("~"), ".cache", "whisper"),
                    timeout=60 * 60,
                )
            except WorkerClientError as exc:
                raise RuntimeError(f"外置本地识别运行时不可用: {exc}") from exc
            self._device = str(payload.get("device", "cpu"))
            return TranscriptionResult(
                segments=[
                    Segment(
                        start_time=float(item.get("start", 0.0)),
                        end_time=float(item.get("end", 0.0)),
                        text=str(item.get("text", "")),
                        confidence=float(item.get("confidence", 0.0)),
                    )
                    for item in payload.get("segments", [])
                    if isinstance(item, dict)
                ],
                language=str(payload.get("language", "unknown")),
                duration=float(payload.get("duration", 0.0)),
            )
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
