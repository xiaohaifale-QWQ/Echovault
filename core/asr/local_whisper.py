"""Local Whisper ASR provider, with optional external GPU-worker execution."""

import logging
import os
from collections.abc import Callable, Sequence
from typing import Optional

from .base import ASRProvider, Segment, TranscriptionResult
from .worker_client import WorkerClient, WorkerClientError

logger = logging.getLogger(__name__)


class LocalWhisperProvider(ASRProvider):
    """Run Whisper locally, or through an isolated CPU/CUDA worker."""

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
            try:
                import whisper  # noqa: F401
            except ImportError as exc:
                raise RuntimeError("openai-whisper not installed") from exc
            try:
                import torch
            except ImportError:
                self._device = "cpu"
            else:
                cuda_available = torch.cuda.is_available()
                self._device = "cuda" if self._use_gpu and cuda_available else "cpu"
                if self._use_gpu and not cuda_available:
                    logger.warning("已启用 GPU，但当前 PyTorch 不支持 CUDA；回退到 CPU")
            logger.info("Loading '%s' (device:%s)...", self._model_name, self._device)
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
        if self._worker_command:
            try:
                report = self._get_worker_client().request("doctor", timeout=10)
                device = report.get("device")
                if isinstance(device, str) and device in {"cpu", "cuda"}:
                    self._device = device
                return bool(report.get("torch_installed"))
            except WorkerClientError:
                return False
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _result_from_payload(payload: dict) -> TranscriptionResult:
        return TranscriptionResult(
            segments=[
                Segment(
                    start_time=float(item.get("start", 0.0)),
                    end_time=float(item.get("end", 0.0)),
                    text=str(item.get("text", "")).strip(),
                    confidence=float(item.get("confidence", item.get("avg_logprob", 0.0))),
                )
                for item in payload.get("segments", [])
                if isinstance(item, dict)
            ],
            language=str(payload.get("language", "unknown")),
            duration=float(payload.get("duration", 0.0)),
        )

    def _transcribe_in_process(
        self, audio_path: str, language: Optional[str], *, relaxed: bool = False
    ) -> TranscriptionResult:
        """Use the bundled model; relaxed mode only applies after an empty GPU result."""
        model = self._get_model()
        lang_map = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}
        options = {}
        if language:
            options["language"] = lang_map.get(language, language)
        if relaxed:
            # Quiet singing is sometimes discarded as silence by a GPU runtime.
            # Keep the material as one whole source and only relax Whisper's gate.
            options.update(
                no_speech_threshold=0.9,
                logprob_threshold=-2.0,
                condition_on_previous_text=False,
            )
        result = model.transcribe(
            audio_path,
            fp16=(self._device == "cuda"),
            verbose=False,
            **options,
        )
        return self._result_from_payload(result)

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> TranscriptionResult:
        if not self._worker_command:
            return self._transcribe_in_process(audio_path, language)
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
        result = self._result_from_payload(payload)
        if not result.is_empty:
            return result

        # New workers understand retry_empty.  Older released workers safely ignore
        # it; the bundled compatibility retry below still makes this useful today.
        try:
            retry_payload = self._get_worker_client().request(
                "transcribe",
                audio=audio_path,
                model=self._model_name,
                language=language,
                cache_dir=os.path.join(os.path.expanduser("~"), ".cache", "whisper"),
                retry_empty=True,
                timeout=60 * 60,
            )
            self._device = str(retry_payload.get("device", self._device))
            retry_result = self._result_from_payload(retry_payload)
            if not retry_result.is_empty:
                return retry_result
        except WorkerClientError:
            logger.warning("External worker empty-result retry failed; using compatibility retry")

        logger.warning("External worker returned no speech; retrying once in compatibility mode")
        return self._transcribe_in_process(audio_path, language, relaxed=True)
