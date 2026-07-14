import sys
from types import ModuleType, SimpleNamespace

from core.asr.local_whisper import LocalWhisperProvider


class FakeModel:
    def __init__(self):
        self.options = None

    def transcribe(self, _audio_path, **options):
        self.options = options
        return {
            "language": "zh",
            "duration": 2.0,
            "segments": [{"start": 0.0, "end": 2.0, "text": "test lyric"}],
        }


def _install_fake_local_model(monkeypatch, model, *, cuda_available):
    loader_module = ModuleType("core.whisper_loader")
    loader_module.load_hf_whisper = lambda *_args, **_kwargs: model
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda_available))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "whisper", ModuleType("whisper"))
    monkeypatch.setitem(sys.modules, "core.whisper_loader", loader_module)


def test_gpu_request_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    model = FakeModel()
    _install_fake_local_model(monkeypatch, model, cuda_available=False)
    provider = LocalWhisperProvider(model_name="tiny", use_gpu=True)

    result = provider.transcribe("audio.wav", language="zh")

    assert model.options["fp16"] is False
    assert result.segments[0].text == "test lyric"


def test_cuda_model_uses_fp16_when_available(monkeypatch):
    model = FakeModel()
    _install_fake_local_model(monkeypatch, model, cuda_available=True)
    provider = LocalWhisperProvider(model_name="tiny", use_gpu=True)

    provider.transcribe("audio.wav")

    assert model.options["fp16"] is True


def test_external_worker_result_is_converted_to_transcription_result():
    class FakeWorker:
        def __init__(self, _command):
            self.requests = []

        def request(self, action, **payload):
            self.requests.append((action, payload))
            if action == "doctor":
                return {"torch_installed": True}
            return {
                "device": "cuda",
                "language": "zh",
                "duration": 2.5,
                "segments": [{"start": 0, "end": 2.5, "text": "worker lyric", "confidence": -0.1}],
            }

    provider = LocalWhisperProvider(
        model_name="medium", worker_command=["worker.exe"], worker_client_factory=FakeWorker
    )
    result = provider.transcribe("audio.wav", language="zh")

    assert provider.is_available() is True
    assert provider.display_name == "本地 Whisper (medium, GPU)"
    assert result.segments[0].text == "worker lyric"


def test_empty_external_result_uses_relaxed_compatibility_retry(monkeypatch):
    class EmptyWorker:
        def __init__(self, _command):
            self.requests = []

        def request(self, action, **payload):
            self.requests.append((action, payload))
            return {"device": "cuda", "language": "zh", "duration": 2.0, "segments": []}

    model = FakeModel()
    _install_fake_local_model(monkeypatch, model, cuda_available=False)
    provider = LocalWhisperProvider(
        model_name="tiny", worker_command=["worker.exe"], worker_client_factory=EmptyWorker
    )
    result = provider.transcribe("audio.wav", language="zh")

    assert result.segments[0].text == "test lyric"
    assert model.options["no_speech_threshold"] == 0.9
    assert model.options["condition_on_previous_text"] is False
    assert provider._worker_client.requests[1][1]["retry_empty"] is True
