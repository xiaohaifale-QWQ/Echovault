import sys
from types import ModuleType, SimpleNamespace

from worker.whisper_service import WhisperService


class FakeModel:
    def transcribe(self, _audio_path, **options):
        self.options = options
        return {
            "language": "zh",
            "duration": 1.5,
            "segments": [{"start": 0, "end": 1.5, "text": "测试", "avg_logprob": -0.2}],
        }


def test_service_uses_cuda_fp16_and_returns_serializable_segments(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"wav")
    model = FakeModel()
    loader_module = ModuleType("core.whisper_loader")
    loader_module.load_hf_whisper = lambda *_args, **_kwargs: model
    fake_torch = SimpleNamespace(
        __version__="test",
        version=SimpleNamespace(cuda="13.2"),
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_name=lambda _index: "Test GPU",
            get_device_capability=lambda _index: (8, 6),
            get_device_properties=lambda _index: SimpleNamespace(total_memory=8 * 1024**3),
            empty_cache=lambda: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "whisper", ModuleType("whisper"))
    monkeypatch.setitem(sys.modules, "core.whisper_loader", loader_module)

    result = WhisperService().transcribe(str(audio), "medium", "zh")

    assert result["device"] == "cuda"
    assert result["segments"][0]["text"] == "测试"
    assert model.options["fp16"] is True
    assert model.options["language"] == "Chinese"
