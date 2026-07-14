import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from core.runtime_manager import RuntimeManagerError
from core.runtime_release import fetch_default_runtime_package, fetch_runtime_package


class _Response:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_fetch_runtime_package_verifies_signed_release_manifest():
    archive = b"runtime-part"
    manifest = {
        "schema_version": 1,
        "variants": {
            "cuda-cu132": {
                "backend": "cuda",
                "version": "1.0.0",
                "archive_size": len(archive),
                "archive_sha256": hashlib.sha256(archive).hexdigest(),
                "installed_size": 1024,
                "worker_path": "worker/echovault-asr-worker.exe",
                "parts": [
                    {
                        "name": "cuda-cu132.zip.part1",
                        "url": "https://github.com/example/cuda-cu132.zip.part1",
                        "size": len(archive),
                        "sha256": hashlib.sha256(archive).hexdigest(),
                    }
                ],
            }
        },
    }
    manifest_bytes = json.dumps(manifest).encode("utf-8")
    private_key = Ed25519PrivateKey.generate()
    signature = private_key.sign(manifest_bytes)
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def opener(request, timeout):
        assert timeout == 30
        content = (
            base64.b64encode(signature)
            if request.full_url.endswith(".sig")
            else manifest_bytes
        )
        return _Response(content)

    package = fetch_runtime_package(
        "cuda-cu132",
        base64.b64encode(public_key).decode("ascii"),
        manifest_url="https://github.com/example/runtime-manifest.json",
        signature_url="https://github.com/example/runtime-manifest.sig",
        opener=opener,
    )

    assert package.runtime_id == "cuda-cu132"
    assert package.worker_path == "worker/echovault-asr-worker.exe"


def test_default_release_requires_embedded_or_configured_public_key(monkeypatch):
    monkeypatch.delenv("ECHOVAULT_RUNTIME_MANIFEST_PUBLIC_KEY", raising=False)

    with pytest.raises(RuntimeManagerError, match="公钥"):
        fetch_default_runtime_package("cuda-cu132")
