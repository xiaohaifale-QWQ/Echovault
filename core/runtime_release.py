"""Fetch an Ed25519-signed runtime manifest from the Echovault GitHub Release."""

import base64
import os
import urllib.request
from collections.abc import Callable

from .runtime_manager import (
    RuntimeManagerError,
    RuntimePackage,
    decode_signature,
    runtime_package_from_manifest,
    verify_manifest_signature,
)

RUNTIME_RELEASE_TAG = "runtime-v1.0"
RUNTIME_RELEASE_BASE_URL = (
    f"https://github.com/xiaohaifale-QWQ/echovault-models/releases/download/{RUNTIME_RELEASE_TAG}"
)
RUNTIME_MANIFEST_URL = f"{RUNTIME_RELEASE_BASE_URL}/runtime-manifest.json"
RUNTIME_SIGNATURE_URL = f"{RUNTIME_RELEASE_BASE_URL}/runtime-manifest.sig"
PUBLIC_KEY_ENVIRONMENT_VARIABLE = "ECHOVAULT_RUNTIME_MANIFEST_PUBLIC_KEY"
# This is the public half of the Ed25519 key stored in the release build system.
# It is safe to ship with the application; only the private signing key can create
# a manifest accepted by this client.
BUILTIN_RUNTIME_MANIFEST_PUBLIC_KEY = "vrG3gELvIpO1I6NxZvV7683OZxYzlrrsihRzDykuRgM="


def fetch_runtime_package(
    runtime_id: str,
    public_key_base64: str,
    *,
    manifest_url: str = RUNTIME_MANIFEST_URL,
    signature_url: str = RUNTIME_SIGNATURE_URL,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> RuntimePackage:
    """Fetch and verify a release manifest before returning a runtime package."""

    public_key = _decode_public_key(public_key_base64)
    manifest_bytes = _download_bytes(manifest_url, opener)
    signature = decode_signature(_download_bytes(signature_url, opener))
    manifest = verify_manifest_signature(manifest_bytes, signature, public_key)
    return runtime_package_from_manifest(manifest, runtime_id)


def fetch_default_runtime_package(runtime_id: str) -> RuntimePackage:
    """Fetch from the official release using the public key embedded by a release build."""

    public_key = os.environ.get(
        PUBLIC_KEY_ENVIRONMENT_VARIABLE, BUILTIN_RUNTIME_MANIFEST_PUBLIC_KEY
    )
    return fetch_runtime_package(runtime_id, public_key)


def _download_bytes(url: str, opener: Callable[..., object]) -> bytes:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Echovault/0.3"})
        response = opener(request, timeout=30)
        with response:
            return response.read()
    except OSError as exc:
        raise RuntimeManagerError(f"无法下载运行时发布清单: {exc}") from exc


def _decode_public_key(value: str) -> bytes:
    try:
        public_key = base64.b64decode(value.strip(), validate=True)
    except ValueError as exc:
        raise RuntimeManagerError("运行时 Release 公钥格式无效") from exc
    if len(public_key) != 32:
        raise RuntimeManagerError("运行时 Release 公钥长度无效")
    return public_key
