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
            "segments": [{"start": 0.0, "end": 2.0, "text": "测试"}],
        }


def test_gpu_request_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    fake_model = FakeModel()
    captured = {}

    def fake_loader(_model_name, cache_dir=None, device="cpu"):
        captured["device"] = device
        return fake_model

    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    fake_loader_module = ModuleType("core.whisper_loader")
    fake_loader_module.load_hf_whisper = fake_loader
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "whisper", ModuleType("whisper"))
    monkeypatch.setitem(sys.modules, "core.whisper_loader", fake_loader_module)
    provider = LocalWhisperProvider(model_name="tiny", use_gpu=True)

    result = provider.transcribe("audio.wav", language="zh")

    assert captured["device"] == "cpu"
    assert fake_model.options["fp16"] is False
    assert result.segments[0].text == "测试"


def test_cuda_model_uses_fp16_when_available(monkeypatch):
    fake_model = FakeModel()
    captured = {}

    def fake_loader(_model_name, cache_dir=None, device="cpu"):
        captured["device"] = device
        return fake_model

    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    fake_loader_module = ModuleType("core.whisper_loader")
    fake_loader_module.load_hf_whisper = fake_loader
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "whisper", ModuleType("whisper"))
    monkeypatch.setitem(sys.modules, "core.whisper_loader", fake_loader_module)
    provider = LocalWhisperProvider(model_name="tiny", use_gpu=True)

    provider.transcribe("audio.wav")

    assert captured["device"] == "cuda"
    assert fake_model.options["fp16"] is True


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
                "segments": [
                    {"start": 0, "end": 2.5, "text": "外置 Worker", "confidence": -0.1}
                ],
            }

    provider = LocalWhisperProvider(
        model_name="medium",
        worker_command=["worker.exe"],
        worker_client_factory=FakeWorker,
    )

    result = provider.transcribe("audio.wav", language="zh")

    assert provider.is_available() is True
    assert provider.display_name == "本地 Whisper (medium, GPU)"
    assert result.segments[0].text == "外置 Worker"
