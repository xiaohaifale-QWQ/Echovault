import hashlib
import sys
from types import SimpleNamespace

from ui.settings_dialog import _file_sha256, _official_model_sha256


def test_file_sha256_streams_complete_file(tmp_path):
    model = tmp_path / "tiny.pt"
    model.write_bytes(b"model-data")

    assert _file_sha256(str(model)) == hashlib.sha256(b"model-data").hexdigest()


def test_official_model_hash_is_well_formed(monkeypatch):
    expected = "a" * 64
    fake_whisper = SimpleNamespace(
        _MODELS={"tiny": f"https://example.test/models/{expected}/tiny.pt"}
    )
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    digest = _official_model_sha256("tiny")

    assert digest == expected
