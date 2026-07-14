"""Split one Worker ZIP and produce an Ed25519-signed runtime Release manifest.

This utility only writes local release assets. Uploading them remains a deliberate
separate action, so the signing private key never needs to be passed to the app.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> int:
    arguments = _arguments()
    archive = arguments.archive.resolve()
    output = arguments.output.resolve()
    metadata = json.loads(arguments.metadata.read_text(encoding="utf-8"))
    _validate_metadata(metadata)
    if not archive.is_file():
        raise SystemExit(f"Runtime archive not found: {archive}")

    private_key = _load_private_key(arguments.private_key.resolve())
    output.mkdir(parents=True, exist_ok=True)
    parts = _split_archive(archive, output, arguments.part_size_mib * 1024 * 1024)
    package = {
        "backend": metadata["backend"],
        "version": arguments.version,
        "archive_size": archive.stat().st_size,
        "archive_sha256": _sha256(archive),
        "installed_size": arguments.installed_size,
        "worker_path": metadata["worker_path"],
        "parts": [
            {
                "name": path.name,
                "url": f"{arguments.release_base_url.rstrip('/')}/{path.name}",
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in parts
        ],
    }
    manifest_path = output / "runtime-manifest.json"
    manifest = _merge_manifest(manifest_path, metadata["runtime_id"], package)
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    signature = base64.b64encode(private_key.sign(manifest_bytes)) + b"\n"
    (output / "runtime-manifest.sig").write_bytes(signature)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    print(f"Public key (embed in the app): {base64.b64encode(public_key).decode('ascii')}")
    print(f"Release assets are ready in: {output}")
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--installed-size", type=int, required=True)
    parser.add_argument("--release-base-url", required=True)
    parser.add_argument("--part-size-mib", type=int, default=512)
    return parser.parse_args()


def _validate_metadata(metadata: object) -> None:
    if not isinstance(metadata, dict):
        raise SystemExit("runtime.json must be a JSON object")
    for key in ("runtime_id", "backend", "worker_path"):
        if not isinstance(metadata.get(key), str) or not metadata[key]:
            raise SystemExit(f"runtime.json is missing {key}")


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"Unable to load Ed25519 private key: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("The signing key must be an Ed25519 private key")
    return key


def _split_archive(archive: Path, output: Path, part_size: int) -> list[Path]:
    if part_size <= 0:
        raise SystemExit("--part-size-mib must be positive")
    part_paths: list[Path] = []
    with archive.open("rb") as source:
        index = 1
        while chunk := source.read(part_size):
            path = output / f"{archive.name}.part{index}"
            path.write_bytes(chunk)
            part_paths.append(path)
            index += 1
    return part_paths


def _merge_manifest(path: Path, runtime_id: str, package: dict[str, object]) -> dict[str, object]:
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Existing manifest is invalid JSON: {exc}") from exc
        if not isinstance(existing, dict) or existing.get("schema_version") != 1:
            raise SystemExit("Existing manifest is not schema version 1")
    else:
        existing = {"schema_version": 1, "variants": {}}
    variants = existing.get("variants")
    if not isinstance(variants, dict):
        raise SystemExit("Existing manifest has no variants object")
    variants[runtime_id] = package
    return existing


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
