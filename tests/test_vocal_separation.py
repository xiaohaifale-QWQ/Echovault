import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import vocal_separation


class _Response:
    status = 200

    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int) -> bytes:
        part = self.payload[self.offset : self.offset + size]
        self.offset += len(part)
        return part

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_download_separation_model_verifies_and_caches(monkeypatch, tmp_path):
    payload = b"valid checkpoint"
    digest = hashlib.sha256(payload).hexdigest()
    spec = vocal_separation.SeparationModel(
        "test", "Test", "Test model", "fast", "good", "1 KB", (f"x/model-{digest[:8]}.th",)
    )
    monkeypatch.setitem(vocal_separation.SEPARATION_MODELS, "test", spec)
    monkeypatch.setitem(vocal_separation.MODEL_BAGS, "test", "models: ['model']\n")
    monkeypatch.setattr(vocal_separation, "model_cache_dir", lambda: tmp_path)
    events = []

    result = vocal_separation.download_separation_model(
        "test",
        progress=lambda percent, message: events.append((percent, message)),
        opener=lambda *_args, **_kwargs: _Response(payload),
    )

    assert result == tmp_path
    assert (tmp_path / f"model-{digest[:8]}.th").read_bytes() == payload
    assert (tmp_path / "test.yaml").is_file()
    assert vocal_separation.separation_model_installed("test")
    assert events[-1][0] == 100


def test_download_separation_model_rejects_bad_hash(monkeypatch, tmp_path):
    spec = vocal_separation.SeparationModel(
        "test", "Test", "", "", "", "", ("x/model-deadbeef.th",)
    )
    monkeypatch.setitem(vocal_separation.SEPARATION_MODELS, "test", spec)
    monkeypatch.setitem(vocal_separation.MODEL_BAGS, "test", "models: ['model']\n")
    monkeypatch.setattr(vocal_separation, "model_cache_dir", lambda: tmp_path)

    with pytest.raises(vocal_separation.SeparationError, match="校验失败"):
        vocal_separation.download_separation_model(
            "test", opener=lambda *_args, **_kwargs: _Response(b"bad")
        )


def test_mix_stems_builds_independent_volume_filter(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(vocal_separation, "find_ffmpeg", lambda: "ffmpeg")

    def fake_run(command, **_kwargs):
        calls.append(command)
        Path(command[-1]).write_bytes(b"mix")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(vocal_separation.subprocess, "run", fake_run)
    output = vocal_separation.mix_stems(
        tmp_path / "vocals.wav",
        tmp_path / "accompaniment.wav",
        tmp_path / "result.wav",
        vocal_volume=70,
        accompaniment_volume=40,
    )

    assert output.read_bytes() == b"mix"
    filter_value = calls[0][calls[0].index("-filter_complex") + 1]
    assert "volume=0.400" in filter_value
    assert "volume=0.700" in filter_value
