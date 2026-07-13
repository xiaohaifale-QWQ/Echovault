import hashlib

from ui.settings_dialog import _file_sha256, _official_model_sha256


def test_file_sha256_streams_complete_file(tmp_path):
    model = tmp_path / "tiny.pt"
    model.write_bytes(b"model-data")

    assert _file_sha256(str(model)) == hashlib.sha256(b"model-data").hexdigest()


def test_official_model_hash_is_well_formed():
    digest = _official_model_sha256("tiny")

    assert len(digest) == 64
    int(digest, 16)
