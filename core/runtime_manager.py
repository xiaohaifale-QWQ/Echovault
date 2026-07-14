"""Signed, resumable installation of external Echovault inference runtimes."""

import base64
import hashlib
import json
import os
import shutil
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

RUNTIME_ROOT_NAME = "Echovault"
SAFETY_MARGIN_BYTES = 512 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]
RuntimeValidator = Callable[[Path], None]


class RuntimeManagerError(RuntimeError):
    """Raised when a managed inference runtime cannot be trusted or installed."""


class RuntimeInstallCancelled(RuntimeManagerError):
    """Raised when the user cancels an install operation."""


@dataclass(frozen=True)
class RuntimePart:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RuntimePackage:
    runtime_id: str
    backend: str
    version: str
    archive_size: int
    archive_sha256: str
    installed_size: int
    worker_path: str
    parts: tuple[RuntimePart, ...]


@dataclass(frozen=True)
class RuntimeInstallResult:
    path: Path
    cached: bool
    activated: bool


def default_runtime_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / RUNTIME_ROOT_NAME


def verify_manifest_signature(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    public_key_bytes: bytes,
) -> dict[str, Any]:
    """Verify an Ed25519-signed manifest before trusting its URLs or hashes."""

    if len(public_key_bytes) != 32:
        raise RuntimeManagerError("运行时清单公钥无效")
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature_bytes, manifest_bytes)
    except (InvalidSignature, ValueError) as exc:
        raise RuntimeManagerError("运行时清单签名校验失败") from exc
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeManagerError("运行时清单不是有效 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeManagerError("运行时清单版本不受支持")
    return manifest


def decode_signature(signature_text: bytes) -> bytes:
    """Decode the base64 signature asset published beside a manifest."""

    try:
        return base64.b64decode(signature_text.strip(), validate=True)
    except ValueError as exc:
        raise RuntimeManagerError("运行时清单签名格式无效") from exc


def runtime_package_from_manifest(manifest: Mapping[str, Any], runtime_id: str) -> RuntimePackage:
    """Read one runtime package after its enclosing manifest has been verified."""

    variants = manifest.get("variants")
    if not isinstance(variants, Mapping):
        raise RuntimeManagerError("运行时清单缺少 variants")
    value = variants.get(runtime_id)
    if not isinstance(value, Mapping):
        raise RuntimeManagerError(f"运行时清单中不存在: {runtime_id}")

    try:
        parts = tuple(
            RuntimePart(
                name=_required_text(part, "name"),
                url=_required_text(part, "url"),
                size=_required_positive_int(part, "size"),
                sha256=_required_sha256(part, "sha256"),
            )
            for part in value["parts"]
        )
        package = RuntimePackage(
            runtime_id=runtime_id,
            backend=_required_text(value, "backend"),
            version=_required_text(value, "version"),
            archive_size=_required_positive_int(value, "archive_size"),
            archive_sha256=_required_sha256(value, "archive_sha256"),
            installed_size=_required_positive_int(value, "installed_size"),
            worker_path=_required_relative_path(value, "worker_path"),
            parts=parts,
        )
    except (KeyError, TypeError) as exc:
        raise RuntimeManagerError("运行时清单字段不完整") from exc
    if not package.parts:
        raise RuntimeManagerError("运行时清单未包含下载分片")
    for part in package.parts:
        _validate_download_url(part.url)
    if sum(part.size for part in package.parts) != package.archive_size:
        raise RuntimeManagerError("运行时分片总大小与归档大小不一致")
    return package


def install_runtime(
    package: RuntimePackage,
    runtime_root: str | os.PathLike[str] | None = None,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    validator: RuntimeValidator | None = None,
    activate: bool = False,
    opener: Callable[..., object] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> RuntimeInstallResult:
    """Download, validate, unpack, validate, and atomically install one runtime."""

    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    root = Path(runtime_root) if runtime_root is not None else default_runtime_root()
    paths = _runtime_paths(root, package.runtime_id)
    for path in (paths["downloads"], paths["temp"], paths["runtimes"]):
        path.mkdir(parents=True, exist_ok=True)

    runtime_dir = paths["runtime_dir"]
    if runtime_dir.exists():
        if _is_valid_installed_runtime(runtime_dir, package):
            if activate:
                activate_runtime(package.runtime_id, root)
            return RuntimeInstallResult(runtime_dir, cached=True, activated=activate)
        raise RuntimeManagerError(f"运行时目录已存在但校验失败: {runtime_dir.name}")

    download_dir = paths["downloads"] / package.runtime_id
    download_dir.mkdir(parents=True, exist_ok=True)
    archive_path = paths["downloads"] / f"{package.runtime_id}.zip"
    staging_dir = paths["temp"] / f"{package.runtime_id}.staging"
    _assert_project_path(root, download_dir)
    _assert_project_path(root, archive_path)
    _assert_project_path(root, staging_dir)

    remaining_download = _remaining_download_bytes(package, download_dir)
    required_free = (
        remaining_download
        + package.archive_size
        + package.installed_size
        + SAFETY_MARGIN_BYTES
    )
    available_free = shutil.disk_usage(root).free
    if available_free < required_free:
        raise RuntimeManagerError(
            "磁盘空间不足：运行时下载和安装还需要约 "
            f"{required_free / 1024 / 1024 / 1024:.1f} GB，"
            f"当前可用 {available_free / 1024 / 1024 / 1024:.1f} GB"
        )

    try:
        total_parts = len(package.parts)
        for index, part in enumerate(package.parts, 1):
            if cancelled():
                raise RuntimeInstallCancelled("运行时下载已取消")
            start = (index - 1) * 70 // total_parts
            span = 70 // total_parts

            def part_progress(
                percent: int,
                message: str,
                *,
                _start: int = start,
                _span: int = span,
                _index: int = index,
            ) -> None:
                progress(
                    _start + percent * _span // 100,
                    f"运行时分片 {_index}/{total_parts} | {message}",
                )

            _download_part(
                part,
                download_dir / part.name,
                progress=part_progress,
                cancelled=cancelled,
                opener=opener,
                sleeper=sleeper,
            )

        progress(72, "正在合并运行时分片...")
        _assemble_archive(
            package,
            download_dir,
            archive_path,
            progress=progress,
            cancelled=cancelled,
        )
        progress(82, "正在安全解压运行时...")
        _extract_archive(archive_path, staging_dir, root)
        _validate_staging(staging_dir, package)
        if validator is not None:
            progress(94, "正在自检推理运行时...")
            validator(staging_dir)
        os.replace(staging_dir, runtime_dir)
        if activate:
            activate_runtime(package.runtime_id, root)
        _cleanup_success(package, download_dir, archive_path, root)
        progress(100, "推理运行时已安装并通过校验")
        return RuntimeInstallResult(runtime_dir, cached=False, activated=activate)
    except Exception:
        _safe_remove_tree(staging_dir, root)
        raise


def activate_runtime(runtime_id: str, runtime_root: str | os.PathLike[str] | None = None) -> None:
    root = Path(runtime_root) if runtime_root is not None else default_runtime_root()
    paths = _runtime_paths(root, runtime_id)
    runtime_dir = paths["runtime_dir"]
    if not runtime_dir.is_dir():
        raise RuntimeManagerError(f"无法启用不存在的运行时: {runtime_id}")
    active_path = paths["runtimes"] / "active.json"
    current = _read_json(active_path)
    previous = current.get("active_runtime") if isinstance(current, dict) else None
    payload = {"active_runtime": runtime_id, "previous_runtime": previous}
    _write_atomic_json(active_path, payload, root)


def active_runtime(runtime_root: str | os.PathLike[str] | None = None) -> str | None:
    root = Path(runtime_root) if runtime_root is not None else default_runtime_root()
    payload = _read_json(root / "runtimes" / "active.json")
    value = payload.get("active_runtime") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def _download_part(
    part: RuntimePart,
    destination: Path,
    *,
    progress: ProgressCallback,
    cancelled: CancelCallback,
    opener: Callable[..., object],
    sleeper: Callable[[float], None],
    max_attempts: int = 5,
) -> None:
    _validate_download_url(part.url)
    if _is_valid_file(destination, part.size, part.sha256):
        progress(100, "已校验，跳过下载")
        return

    partial = destination.with_name(destination.name + ".download")
    for attempt in range(1, max_attempts + 1):
        if cancelled():
            raise RuntimeInstallCancelled("运行时下载已取消")
        existing = partial.stat().st_size if partial.exists() else 0
        if existing > part.size:
            partial.unlink()
            existing = 0
        headers = {"User-Agent": "Echovault/0.3"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(part.url, headers=headers)
        try:
            response = opener(request, timeout=60)
            status = getattr(response, "status", 200)
            resumed = bool(existing and status == 206)
            received = existing if resumed else 0
            mode = "ab" if resumed else "wb"
            with response, open(partial, mode) as file_handle:
                while True:
                    if cancelled():
                        raise RuntimeInstallCancelled("运行时下载已取消")
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    file_handle.write(chunk)
                    received += len(chunk)
                    if received > part.size:
                        raise RuntimeManagerError("服务器返回的数据大于运行时分片大小")
                    progress(min(99, int(received * 100 / part.size)), "GitHub Release 下载中")
            if received != part.size:
                raise RuntimeManagerError("运行时分片下载不完整")
        except RuntimeInstallCancelled:
            raise
        except (OSError, TimeoutError, urllib.error.URLError, RuntimeManagerError) as exc:
            if attempt == max_attempts:
                raise RuntimeManagerError(f"运行时分片下载失败: {exc}") from exc
            wait = 2 ** (attempt - 1)
            progress(0, f"连接中断，{wait} 秒后重试 ({attempt + 1}/{max_attempts})...")
            sleeper(wait)
            continue

        if not _is_valid_file(partial, part.size, part.sha256):
            partial.unlink(missing_ok=True)
            raise RuntimeManagerError("运行时分片 SHA-256 校验失败，损坏文件已删除")
        os.replace(partial, destination)
        progress(100, "下载及校验完成")
        return


def _assemble_archive(
    package: RuntimePackage,
    download_dir: Path,
    archive_path: Path,
    *,
    progress: ProgressCallback,
    cancelled: CancelCallback,
) -> None:
    assembling = archive_path.with_name(archive_path.name + ".assembling")
    assembling.unlink(missing_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        with open(assembling, "xb") as output:
            for part in package.parts:
                with open(download_dir / part.name, "rb") as source:
                    while True:
                        if cancelled():
                            raise RuntimeInstallCancelled("运行时合并已取消")
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        progress(
                            72 + min(9, int(written * 9 / package.archive_size)),
                            "正在合并运行时",
                        )
        if written != package.archive_size or digest.hexdigest() != package.archive_sha256:
            raise RuntimeManagerError("运行时完整归档 SHA-256 校验失败")
        os.replace(assembling, archive_path)
    except Exception:
        assembling.unlink(missing_ok=True)
        raise


def _extract_archive(archive_path: Path, staging_dir: Path, root: Path) -> None:
    _safe_remove_tree(staging_dir, root)
    staging_dir.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                relative = PurePosixPath(info.filename)
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise RuntimeManagerError("运行时归档包含不安全路径")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise RuntimeManagerError("运行时归档不能包含符号链接")
                destination = staging_dir.joinpath(*relative.parts)
                _assert_project_path(root, destination)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(destination, "wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise RuntimeManagerError("运行时归档不是有效 ZIP 文件") from exc


def _validate_staging(staging_dir: Path, package: RuntimePackage) -> None:
    runtime_json = _read_json(staging_dir / "runtime.json")
    if runtime_json.get("runtime_id") != package.runtime_id:
        raise RuntimeManagerError("运行时目录缺少匹配的 runtime.json")
    worker_path = staging_dir.joinpath(*PurePosixPath(package.worker_path).parts)
    if not worker_path.is_file():
        raise RuntimeManagerError("运行时目录缺少 ASR Worker")


def _is_valid_installed_runtime(runtime_dir: Path, package: RuntimePackage) -> bool:
    try:
        _validate_staging(runtime_dir, package)
    except RuntimeManagerError:
        return False
    return True


def _remaining_download_bytes(package: RuntimePackage, download_dir: Path) -> int:
    remaining = 0
    for part in package.parts:
        destination = download_dir / part.name
        if _is_valid_file(destination, part.size, part.sha256):
            continue
        partial = destination.with_name(destination.name + ".download")
        existing = partial.stat().st_size if partial.exists() else 0
        remaining += max(0, part.size - min(existing, part.size))
    return remaining


def _cleanup_success(
    package: RuntimePackage,
    download_dir: Path,
    archive_path: Path,
    root: Path,
) -> None:
    for part in package.parts:
        (download_dir / part.name).unlink(missing_ok=True)
        (download_dir / f"{part.name}.download").unlink(missing_ok=True)
    archive_path.unlink(missing_ok=True)
    archive_path.with_name(archive_path.name + ".assembling").unlink(missing_ok=True)
    if download_dir.exists() and not any(download_dir.iterdir()):
        _safe_remove_tree(download_dir, root)


def _runtime_paths(root: Path, runtime_id: str) -> dict[str, Path]:
    if not runtime_id or any(part in {"", ".", ".."} for part in Path(runtime_id).parts):
        raise RuntimeManagerError("运行时 ID 无效")
    root = root.resolve()
    paths = {
        "root": root,
        "downloads": root / "downloads",
        "temp": root / "temp",
        "runtimes": root / "runtimes",
        "runtime_dir": root / "runtimes" / runtime_id,
    }
    for path in paths.values():
        _assert_project_path(root, path)
    return paths


def _assert_project_path(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeManagerError("运行时操作路径超出 Echovault 项目目录") from exc


def _safe_remove_tree(path: Path, root: Path) -> None:
    if path.exists():
        _assert_project_path(root, path)
        shutil.rmtree(path)


def _is_valid_file(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and path.stat().st_size == size and _sha256(path) == sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_download_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise RuntimeManagerError("运行时下载地址不在受信任的 GitHub Release 域名内")


def _required_text(value: Mapping[str, Any], key: str) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeManagerError(f"运行时清单字段无效: {key}")
    return text


def _required_positive_int(value: Mapping[str, Any], key: str) -> int:
    number = value.get(key)
    if not isinstance(number, int) or number <= 0:
        raise RuntimeManagerError(f"运行时清单字段无效: {key}")
    return number


def _required_sha256(value: Mapping[str, Any], key: str) -> str:
    digest = _required_text(value, key).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeManagerError(f"运行时清单 SHA-256 无效: {key}")
    return digest


def _required_relative_path(value: Mapping[str, Any], key: str) -> str:
    path = PurePosixPath(_required_text(value, key))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RuntimeManagerError(f"运行时清单路径无效: {key}")
    return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_atomic_json(path: Path, value: Mapping[str, Any], root: Path) -> None:
    _assert_project_path(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    _assert_project_path(root, temporary)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
