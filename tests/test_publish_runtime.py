import base64
import json
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.runtime_manager import verify_manifest_signature


def test_publish_runtime_splits_archive_and_signs_manifest(tmp_path):
    archive = tmp_path / "cuda-cu132.zip"
    archive.write_bytes(b"abcdefghij")
    metadata = tmp_path / "runtime.json"
    metadata.write_text(
        json.dumps(
            {
                "runtime_id": "cuda-cu132",
                "backend": "cuda",
                "worker_path": "worker/echovault-asr-worker.exe",
            }
        ),
        encoding="utf-8",
    )
    private_key = Ed25519PrivateKey.generate()
    private_key_path = tmp_path / "release-key.pem"
    private_key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    output = tmp_path / "assets"

    result = subprocess.run(
        [
            sys.executable,
            "tools/publish_runtime.py",
            "--archive",
            str(archive),
            "--metadata",
            str(metadata),
            "--private-key",
            str(private_key_path),
            "--output",
            str(output),
            "--version",
            "1.0.0",
            "--installed-size",
            "100",
            "--release-base-url",
            "https://github.com/xiaohaifale-QWQ/echovault-models/releases/download/v1.0",
            "--part-size-mib",
            "1",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    manifest_bytes = (output / "runtime-manifest.json").read_bytes()
    signature = base64.b64decode((output / "runtime-manifest.sig").read_bytes())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    manifest = verify_manifest_signature(manifest_bytes, signature, public_key)

    assert manifest["variants"]["cuda-cu132"]["archive_size"] == 10
    assert (output / "cuda-cu132.zip.part1").read_bytes() == b"abcdefghij"
    assert "Public key (embed in the app):" in result.stdout
