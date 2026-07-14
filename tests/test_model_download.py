import hashlib
import io
from types import SimpleNamespace

import pytest

from core import model_download
from core.model_download import ModelAsset, ModelDownloadError, download_model, file_sha256


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_release_manifest_points_to_owner_repository():
    assert model_download.RELEASE_BASE_URL == (
        "https://github.com/xiaohaifale-QWQ/echovault-models/releases/download/v1.0"
    )
    assert set(model_download.MODEL_ASSETS) == {"tiny", "base", "small"}
    assert all(len(asset.sha256) == 64 for asset in model_download.MODEL_ASSETS.values())
    assert [asset.file_name for asset in model_download.MEDIUM_ASSETS] == [
        "medium.part1",
        "medium.part2",
    ]
    assert sum(asset.size for asset in model_download.MEDIUM_ASSETS) == 3_055_735_323


def test_file_sha256_streams_complete_file(tmp_path):
    model = tmp_path / "tiny.pt"
    model.write_bytes(b"model-data")

    assert file_sha256(model) == hashlib.sha256(b"model-data").hexdigest()


def test_download_uses_release_asset_and_validates_hash(tmp_path, monkeypatch):
    payload = b"release-model"
    asset = ModelAsset("tiny.pt", len(payload), hashlib.sha256(payload).hexdigest())
    monkeypatch.setitem(model_download.MODEL_ASSETS, "tiny", asset)
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "tiny", {asset.sha256})
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, request.headers, timeout))
        return FakeResponse(payload)

    result = download_model("tiny", tmp_path, opener=opener, sleeper=lambda _wait: None)

    assert result.path.read_bytes() == payload
    assert result.cached is False
    assert requests[0][0].endswith("/v1.0/tiny.pt")
    assert not (tmp_path / "tiny.pt.download").exists()


def test_download_resumes_partial_file(tmp_path, monkeypatch):
    payload = b"0123456789"
    asset = ModelAsset("tiny.pt", len(payload), hashlib.sha256(payload).hexdigest())
    monkeypatch.setitem(model_download.MODEL_ASSETS, "tiny", asset)
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "tiny", {asset.sha256})
    (tmp_path / "tiny.pt.download").write_bytes(payload[:4])

    def opener(request, timeout):
        assert request.get_header("Range") == "bytes=4-"
        return FakeResponse(payload[4:], status=206)

    result = download_model("tiny", tmp_path, opener=opener, sleeper=lambda _wait: None)

    assert result.path.read_bytes() == payload


def test_valid_cached_model_skips_network(tmp_path, monkeypatch):
    payload = b"cached-model"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "tiny", {digest})
    (tmp_path / "tiny.pt").write_bytes(payload)

    result = download_model(
        "tiny",
        tmp_path,
        opener=lambda *_args, **_kwargs: pytest.fail("network should not be used"),
    )

    assert result.cached is True


def test_medium_downloads_parts_merges_and_removes_them(tmp_path, monkeypatch):
    first = b"medium-first-"
    second = b"medium-second"
    assets = (
        ModelAsset("medium.part1", len(first), hashlib.sha256(first).hexdigest()),
        ModelAsset("medium.part2", len(second), hashlib.sha256(second).hexdigest()),
    )
    full_digest = hashlib.sha256(first + second).hexdigest()
    monkeypatch.setattr(model_download, "MEDIUM_ASSETS", assets)
    monkeypatch.setattr(model_download, "MEDIUM_RELEASE_SHA256", full_digest)
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "medium", {full_digest})
    requests = []

    def opener(request, timeout):
        requests.append(request.full_url)
        payload = first if request.full_url.endswith("medium.part1") else second
        return FakeResponse(payload)

    result = download_model("medium", tmp_path, opener=opener, sleeper=lambda _wait: None)

    assert result.path.read_bytes() == first + second
    assert requests[0].endswith("medium.part1")
    assert requests[1].endswith("medium.part2")
    assert not (tmp_path / "medium.part1").exists()
    assert not (tmp_path / "medium.part2").exists()
    assert not (tmp_path / "medium.pt.assembling").exists()


def test_medium_reuses_verified_part_and_only_downloads_missing_part(tmp_path, monkeypatch):
    first = b"already-downloaded"
    second = b"missing-part"
    assets = (
        ModelAsset("medium.part1", len(first), hashlib.sha256(first).hexdigest()),
        ModelAsset("medium.part2", len(second), hashlib.sha256(second).hexdigest()),
    )
    full_digest = hashlib.sha256(first + second).hexdigest()
    monkeypatch.setattr(model_download, "MEDIUM_ASSETS", assets)
    monkeypatch.setattr(model_download, "MEDIUM_RELEASE_SHA256", full_digest)
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "medium", {full_digest})
    (tmp_path / "medium.part1").write_bytes(first)

    def opener(request, timeout):
        assert request.full_url.endswith("medium.part2")
        return FakeResponse(second)

    result = download_model("medium", tmp_path, opener=opener, sleeper=lambda _wait: None)

    assert result.path.read_bytes() == first + second


def test_medium_cancellation_removes_assembling_file_but_keeps_verified_parts(
    tmp_path, monkeypatch
):
    first = b"first"
    second = b"second"
    assets = (
        ModelAsset("medium.part1", len(first), hashlib.sha256(first).hexdigest()),
        ModelAsset("medium.part2", len(second), hashlib.sha256(second).hexdigest()),
    )
    full_digest = hashlib.sha256(first + second).hexdigest()
    monkeypatch.setattr(model_download, "MEDIUM_ASSETS", assets)
    monkeypatch.setattr(model_download, "MEDIUM_RELEASE_SHA256", full_digest)
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "medium", {full_digest})
    (tmp_path / "medium.part1").write_bytes(first)
    (tmp_path / "medium.part2").write_bytes(second)
    cancel_merge = False

    def progress(_percent, message):
        nonlocal cancel_merge
        if "已校验" in message and "2/2" in message:
            cancel_merge = True

    with pytest.raises(model_download.DownloadCancelled):
        download_model(
            "medium",
            tmp_path,
            progress=progress,
            cancelled=lambda: cancel_merge,
            opener=lambda *_args, **_kwargs: pytest.fail("network should not be used"),
        )

    assert (tmp_path / "medium.part1").read_bytes() == first
    assert (tmp_path / "medium.part2").read_bytes() == second
    assert not (tmp_path / "medium.pt.assembling").exists()


def test_medium_checks_peak_disk_space_before_network(tmp_path, monkeypatch):
    first = b"first"
    second = b"second"
    assets = (
        ModelAsset("medium.part1", len(first), hashlib.sha256(first).hexdigest()),
        ModelAsset("medium.part2", len(second), hashlib.sha256(second).hexdigest()),
    )
    monkeypatch.setattr(model_download, "MEDIUM_ASSETS", assets)
    monkeypatch.setattr(model_download.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))

    with pytest.raises(ModelDownloadError, match="磁盘空间不足"):
        download_model(
            "medium",
            tmp_path,
            opener=lambda *_args, **_kwargs: pytest.fail("network should not be used"),
        )


def test_corrupt_download_is_deleted(tmp_path, monkeypatch):
    expected = b"expected"
    corrupt = b"corrupt!"
    asset = ModelAsset("tiny.pt", len(expected), hashlib.sha256(expected).hexdigest())
    monkeypatch.setitem(model_download.MODEL_ASSETS, "tiny", asset)
    monkeypatch.setitem(model_download.ACCEPTED_MODEL_HASHES, "tiny", {asset.sha256})

    with pytest.raises(ModelDownloadError, match="SHA-256"):
        download_model(
            "tiny",
            tmp_path,
            opener=lambda *_args, **_kwargs: FakeResponse(corrupt),
            sleeper=lambda _wait: None,
        )

    assert not (tmp_path / "tiny.pt").exists()
    assert not (tmp_path / "tiny.pt.download").exists()
