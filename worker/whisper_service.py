"""Whisper implementation used inside CPU/CUDA external ASR workers."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]


class WorkerCommandError(RuntimeError):
    """A structured worker error safe to return through the JSON protocol."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class WhisperService:
    """Load and reuse one Whisper model in the worker process."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._device = "cpu"

    def doctor(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "torch_installed": False,
            "cuda_available": False,
            "device": "cpu",
        }
        try:
            import torch
        except ImportError:
            return report

        report["torch_installed"] = True
        report["torch_version"] = getattr(torch, "__version__", "unknown")
        report["torch_cuda_version"] = getattr(getattr(torch, "version", None), "cuda", None)
        try:
            cuda_available = bool(torch.cuda.is_available())
        except Exception as exc:
            report["cuda_error"] = str(exc)
            return report
        report["cuda_available"] = cuda_available
        if not cuda_available:
            return report

        report["device"] = "cuda"
        try:
            report["gpu_name"] = torch.cuda.get_device_name(0)
            report["compute_capability"] = list(torch.cuda.get_device_capability(0))
            total_memory = torch.cuda.get_device_properties(0).total_memory
            report["total_memory_mib"] = int(total_memory / 1024**2)
        except Exception as exc:
            report["cuda_error"] = str(exc)
        return report

    def transcribe(
        self,
        audio_path: str,
        model_name: str,
        language: str | None,
        cache_dir: str | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        if not Path(audio_path).is_file():
            raise WorkerCommandError("AUDIO_NOT_FOUND", f"找不到音频文件: {audio_path}")
        progress = progress or (lambda _percent, _message: None)
        progress(5, "正在检查推理设备...")
        model = self._get_model(model_name, cache_dir, progress)
        options: dict[str, Any] = {"fp16": self._device == "cuda", "verbose": False}
        if language:
            options["language"] = _language_name(language)
        progress(25, f"正在使用 {'GPU' if self._device == 'cuda' else 'CPU'} 识别...")
        try:
            result = model.transcribe(audio_path, **options)
        except RuntimeError as exc:
            if self._device == "cuda" and _is_cuda_memory_error(exc):
                self.release_model()
                raise WorkerCommandError(
                    "CUDA_OOM",
                    "GPU 显存不足，无法加载或识别当前模型。请改用更小模型或 CPU。",
                    retryable=True,
                ) from exc
            raise WorkerCommandError(
                "TRANSCRIBE_FAILED",
                f"本地识别失败: {exc}",
                retryable=True,
            ) from exc

        progress(95, "正在整理识别结果...")
        segments = []
        for segment in result.get("segments", []):
            segments.append(
                {
                    "start": float(segment.get("start", 0.0)),
                    "end": float(segment.get("end", 0.0)),
                    "text": str(segment.get("text", "")).strip(),
                    "confidence": float(segment.get("avg_logprob", 0.0)),
                }
            )
        progress(100, "识别完成")
        return {
            "segments": segments,
            "language": str(result.get("language", "unknown")),
            "duration": float(result.get("duration", 0.0)),
            "device": self._device,
            "model": model_name,
        }

    def release_model(self) -> None:
        self._model = None
        self._model_name = None
        if self._device == "cuda":
            try:
                import torch

                torch.cuda.empty_cache()
            except (ImportError, AttributeError, RuntimeError):
                pass

    def _get_model(
        self,
        model_name: str,
        cache_dir: str | None,
        progress: ProgressCallback,
    ) -> Any:
        if self._model is not None and self._model_name == model_name:
            return self._model
        self.release_model()
        try:
            import torch
            import whisper  # noqa: F401 - verifies the runtime has Whisper installed.
        except ImportError as exc:
            raise WorkerCommandError(
                "DEPENDENCY_MISSING",
                "推理运行时缺少 Torch 或 Whisper，请重新安装运行时。",
            ) from exc

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            self._device = "cpu"
        device_name = "GPU" if self._device == "cuda" else "CPU"
        progress(10, f"正在加载 {model_name} 模型到 {device_name}...")
        try:
            from core.whisper_loader import load_hf_whisper

            self._model = load_hf_whisper(model_name, cache_dir=cache_dir, device=self._device)
            self._model_name = model_name
            return self._model
        except FileNotFoundError as exc:
            raise WorkerCommandError(
                "MODEL_MISSING",
                f"本地未找到 {model_name} 模型，请先在软件中下载模型。",
            ) from exc
        except RuntimeError as exc:
            if self._device == "cuda" and _is_cuda_memory_error(exc):
                self.release_model()
                raise WorkerCommandError(
                    "CUDA_OOM",
                    "GPU 显存不足，无法加载当前模型。请改用更小模型或 CPU。",
                    retryable=True,
                ) from exc
            raise


def _language_name(language: str) -> str:
    return {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}.get(
        language.lower(), language
    )


def _is_cuda_memory_error(error: RuntimeError) -> bool:
    message = str(error).lower()
    return "out of memory" in message or "cuda oom" in message
