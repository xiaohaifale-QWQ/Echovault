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

    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    monkeypatch.setattr("core.whisper_loader.load_hf_whisper", fake_loader)
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

    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    monkeypatch.setattr("core.whisper_loader.load_hf_whisper", fake_loader)
    provider = LocalWhisperProvider(model_name="tiny", use_gpu=True)

    provider.transcribe("audio.wav")

    assert captured["device"] == "cuda"
    assert fake_model.options["fp16"] is True
