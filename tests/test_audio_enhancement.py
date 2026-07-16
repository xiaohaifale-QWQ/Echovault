import hashlib
import logging
import sys
import types
from pathlib import Path

from core import audio_enhancement
from core.audio_enhancement import EnhancementModel


def _test_model(payload: bytes = b"model") -> EnhancementModel:
    return EnhancementModel(
        "test",
        "Test Enhancer",
        "test",
        "fast",
        "high",
        "5 bytes",
        "test.pth",
        "Clean",
        hashlib.md5(payload, usedforsecurity=False).hexdigest(),
    )


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int) -> bytes:
        block = self.payload[self.offset : self.offset + size]
        self.offset += len(block)
        return block


def test_download_enhancement_model_installs_verified_files(monkeypatch, tmp_path):
    model_payload = b"model"
    monkeypatch.setattr(audio_enhancement, "ENHANCEMENT_MODELS", {"test": _test_model()})
    monkeypatch.setattr(audio_enhancement, "enhancement_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        audio_enhancement,
        "_METADATA_FILES",
        {"metadata.json": "https://example.invalid/metadata.json"},
    )
    progress = []

    checkpoint = audio_enhancement.download_enhancement_model(
        "test",
        progress=lambda percent, message: progress.append((percent, message)),
        opener=lambda url: _Response(
            model_payload if url.endswith("test.pth") else b"{}"
        ),
    )

    assert checkpoint.read_bytes() == model_payload
    assert (tmp_path / "metadata.json").read_bytes() == b"{}"
    assert audio_enhancement.enhancement_model_installed("test")
    assert progress[-1][0] == 100


def test_enhance_audio_writes_requested_clean_stem(monkeypatch, tmp_path):
    source = tmp_path / "source.wav"
    output = tmp_path / "clean.wav"
    source.write_bytes(b"source")
    monkeypatch.setattr(audio_enhancement, "ENHANCEMENT_MODELS", {"test": _test_model()})
    monkeypatch.setattr(audio_enhancement, "enhancement_available", lambda: True)
    monkeypatch.setattr(audio_enhancement, "enhancement_model_installed", lambda _key: True)
    monkeypatch.setattr(audio_enhancement, "enhancement_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(audio_enhancement, "find_ffmpeg", lambda: str(tmp_path / "ffmpeg.exe"))

    class FakeSeparator:
        def __init__(self, **kwargs):
            self.output_dir = Path(kwargs["output_dir"])
            self.logger = logging.getLogger("test-audio-enhancement")

        def load_model(self, filename):
            assert filename == "test.pth"

        def separate(self, _source, custom_output_names):
            assert custom_output_names == {"Clean": "source_test_clean"}
            rendered = self.output_dir / "source_test_clean.wav"
            rendered.write_bytes(b"clean")
            # Some frozen audio-separator builds write the file but return an empty list.
            return []

    separator_module = types.ModuleType("audio_separator.separator")
    separator_module.Separator = FakeSeparator
    package_module = types.ModuleType("audio_separator")
    package_module.separator = separator_module
    torch_module = types.ModuleType("torch")
    torch_module.device = lambda name: name
    monkeypatch.setitem(sys.modules, "audio_separator", package_module)
    monkeypatch.setitem(sys.modules, "audio_separator.separator", separator_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    result = audio_enhancement.enhance_audio(
        source, output, model="test", progress=lambda *_args: None
    )

    assert result == output
    assert output.read_bytes() == b"clean"
