import base64
import hashlib
import io
import json
import shutil
import zipfile
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.runtime_manager import (
    RuntimeInstallCancelled,
    RuntimeManagerError,
    RuntimePackage,
    RuntimePart,
    _format_transfer_status,
    active_runtime,
    active_worker_command,
    decode_signature,
    install_runtime,
    runtime_package_from_manifest,
    verify_manifest_signature,
)


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _runtime_archive(runtime_id: str = "cuda-cu132") -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "runtime.json",
            json.dumps({"runtime_id": runtime_id, "worker_path": "bin/echovault-asr-worker.exe"}),
        )
        archive.writestr("bin/echovault-asr-worker.exe", b"worker")
    return content.getvalue()


def _package(payload: bytes, runtime_id: str = "cuda-cu132") -> RuntimePackage:
    split = len(payload) // 2
    first, second = payload[:split], payload[split:]
    return RuntimePackage(
        runtime_id=runtime_id,
        backend="cuda",
        version="1.0.0",
        archive_size=len(payload),
        archive_sha256=_sha(payload),
        installed_size=4096,
        worker_path="bin/echovault-asr-worker.exe",
        parts=(
            RuntimePart(
                "runtime.part1",
                "https://github.com/example/runtime.part1",
                len(first),
                _sha(first),
            ),
            RuntimePart(
                "runtime.part2",
                "https://github.com/example/runtime.part2",
                len(second),
                _sha(second),
            ),
        ),
    )


def test_signed_manifest_is_verified_before_package_is_read():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    manifest = {
        "schema_version": 1,
        "variants": {
            "cpu": {
                "backend": "cpu",
                "version": "1.0.0",
                "archive_size": 10,
                "archive_sha256": "a" * 64,
                "installed_size": 100,
                "worker_path": "worker.exe",
                "parts": [
                    {
                        "name": "part1",
                        "url": "https://github.com/example/part1",
                        "size": 10,
                        "sha256": "a" * 64,
                    }
                ],
            }
        },
    }
    raw = json.dumps(manifest, separators=(",", ":")).encode()
    signature = private.sign(raw)

    verified = verify_manifest_signature(raw, signature, public)
    package = runtime_package_from_manifest(verified, "cpu")

    assert package.runtime_id == "cpu"
    assert decode_signature(base64.b64encode(signature)) == signature
    with pytest.raises(RuntimeManagerError, match="签名"):
        verify_manifest_signature(raw + b" ", signature, public)


def test_install_runtime_assembles_validates_activates_and_cleans_parts(tmp_path):
    payload = _runtime_archive()
    package = _package(payload)
    requested = []

    def opener(request, timeout):
        requested.append(request.full_url)
        data = payload[: len(payload) // 2]
        if not request.full_url.endswith("part1"):
            data = payload[len(payload) // 2 :]
        return FakeResponse(data)

    result = install_runtime(
        package,
        tmp_path,
        activate=True,
        opener=opener,
        sleeper=lambda _wait: None,
    )

    assert result.cached is False
    assert result.activated is True
    assert (result.path / "bin" / "echovault-asr-worker.exe").read_bytes() == b"worker"
    assert active_runtime(tmp_path) == "cuda-cu132"
    assert active_worker_command(tmp_path) == [
        str(result.path / "bin" / "echovault-asr-worker.exe")
    ]
    assert len(requested) == 2
    assert not (tmp_path / "downloads" / "cuda-cu132.zip").exists()
    assert not (tmp_path / "downloads" / "cuda-cu132").exists()


def test_install_runtime_reuses_verified_parts_and_handles_cancellation(tmp_path):
    payload = _runtime_archive()
    package = _package(payload)
    download_dir = tmp_path / "downloads" / package.runtime_id
    download_dir.mkdir(parents=True)
    first = payload[: len(payload) // 2]
    (download_dir / "runtime.part1").write_bytes(first)

    with pytest.raises(RuntimeInstallCancelled):
        install_runtime(
            package,
            tmp_path,
            cancelled=lambda: True,
            opener=lambda *_args, **_kwargs: pytest.fail("network should not be used"),
        )

    assert (download_dir / "runtime.part1").read_bytes() == first


def test_install_runtime_checks_disk_before_network(tmp_path, monkeypatch):
    payload = _runtime_archive()
    package = _package(payload)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))

    with pytest.raises(RuntimeManagerError, match="磁盘空间不足"):
        install_runtime(
            package,
            tmp_path,
            opener=lambda *_args, **_kwargs: pytest.fail("network should not be used"),
        )


def test_install_runtime_rejects_zip_path_escape(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../outside.txt", "bad")
    package = RuntimePackage(
        runtime_id="cpu",
        backend="cpu",
        version="1.0.0",
        archive_size=len(payload.getvalue()),
        archive_sha256=_sha(payload.getvalue()),
        installed_size=100,
        worker_path="worker.exe",
        parts=(
            RuntimePart(
                "part1",
                "https://github.com/example/part1",
                len(payload.getvalue()),
                _sha(payload.getvalue()),
            ),
        ),
    )

    with pytest.raises(RuntimeManagerError, match="不安全路径"):
        install_runtime(
            package,
            tmp_path,
            opener=lambda *_args, **_kwargs: FakeResponse(payload.getvalue()),
            sleeper=lambda _wait: None,
        )

    assert not (tmp_path / "outside.txt").exists()
    assert not (tmp_path / "temp" / "cpu.staging").exists()


def test_transfer_status_displays_rate_amount_and_remaining_time():
    status = _format_transfer_status(
        6 * 1024 * 1024,
        10 * 1024 * 1024,
        4 * 1024 * 1024,
        2.0,
    )

    assert status == "2.0 MB/s | 已下载 6.0 MB/10.0 MB | 预计剩余 00:02"
    assert "测速中" in _format_transfer_status(1024, 2048, 1024, 0.1)


def test_runtime_metadata_accepts_utf8_bom(tmp_path):
    runtime = tmp_path / "runtimes" / "cuda-cu132"
    worker = runtime / "bin" / "echovault-asr-worker.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    (runtime / "runtime.json").write_text(
        json.dumps({"worker_path": "bin/echovault-asr-worker.exe"}),
        encoding="utf-8-sig",
    )
    (tmp_path / "runtimes" / "active.json").write_text(
        json.dumps({"active_runtime": "cuda-cu132"}),
        encoding="utf-8",
    )

    assert active_worker_command(tmp_path) == [str(worker)]
