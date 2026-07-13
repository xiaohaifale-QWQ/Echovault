"""Download and verify Whisper checkpoints from the Echovault model release."""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RELEASE_TAG = "v1.0"
RELEASE_BASE_URL = (
    f"https://github.com/xiaohaifale-QWQ/echovault-models/releases/download/{RELEASE_TAG}"
)


@dataclass(frozen=True)
class ModelAsset:
    file_name: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"{RELEASE_BASE_URL}/{self.file_name}"


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    cached: bool


class ModelDownloadError(RuntimeError):
    """Raised when a model cannot be downloaded or validated."""


class DownloadCancelled(ModelDownloadError):
    """Raised when the caller requests cancellation."""


# This manifest is copied from GitHub's release API. Keeping it in the application
# means downloads do not depend on API rate limits and every asset is authenticated.
MODEL_ASSETS = {
    "tiny": ModelAsset(
        "tiny.pt",
        151_095_027,
        "9607f98a2b22d9e229ae43c52ecea79dcede9e0c5cfae67e8da6eda86d8aac1d",
    ),
    "base": ModelAsset(
        "base.pt",
        145_262_807,
        "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
    ),
    "small": ModelAsset(
        "small.pt",
        967_092_419,
        "ea40d8f6c99cada3695b9ddec20d5ee228a58292650b79c94d8600f567bf9b37",
    ),
}

# Existing official OpenAI checkpoints remain valid, even when their hash differs
# from the checkpoint mirrored in the Echovault release.
ACCEPTED_MODEL_HASHES = {
    "tiny": {
        MODEL_ASSETS["tiny"].sha256,
        "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
    },
    "base": {MODEL_ASSETS["base"].sha256},
    "small": {
        MODEL_ASSETS["small"].sha256,
        "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
    },
    "medium": {"345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1"},
}

UNAVAILABLE_MODELS = {
    "medium": (
        "GitHub Release v1.0 目前只有 medium.part1，缺少 medium.part2。"
        "为避免浪费约 1.5 GB 空间，本次不会开始下载；补齐第二个分片后即可支持。"
    )
}

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "whisper"


def file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_cached_model(path: Path, model: str) -> bool:
    accepted = ACCEPTED_MODEL_HASHES.get(model, set())
    return path.is_file() and bool(accepted) and file_sha256(path) in accepted


def download_model(
    model: str,
    cache_dir: str | os.PathLike[str] | None = None,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> DownloadResult:
    """Download one model into the standard Whisper cache.

    Network interruptions preserve the ``.download`` file for the next attempt.
    Files that fail size or SHA-256 validation are deleted because they cannot be
    resumed safely.
    """

    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    target_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    model_path = target_dir / f"{model}.pt"

    if model_path.exists():
        progress(0, f"正在校验 {model} 模型...")
        if _is_valid_cached_model(model_path, model):
            return DownloadResult(model_path, cached=True)
        model_path.unlink()

    if model in UNAVAILABLE_MODELS:
        raise ModelDownloadError(UNAVAILABLE_MODELS[model])
    if model not in MODEL_ASSETS:
        raise ModelDownloadError(f"不支持的模型: {model}")
    if cancelled():
        raise DownloadCancelled("下载已取消")

    asset = MODEL_ASSETS[model]
    _download_asset(
        asset,
        model_path,
        progress=progress,
        cancelled=cancelled,
        opener=opener,
        sleeper=sleeper,
    )
    return DownloadResult(model_path, cached=False)


def _download_asset(
    asset: ModelAsset,
    destination: Path,
    *,
    progress: ProgressCallback,
    cancelled: CancelCallback,
    opener: Callable[..., object],
    sleeper: Callable[[float], None],
    max_attempts: int = 5,
) -> None:
    partial_path = destination.with_name(destination.name + ".download")

    for attempt in range(1, max_attempts + 1):
        if cancelled():
            raise DownloadCancelled("下载已取消")

        existing = partial_path.stat().st_size if partial_path.exists() else 0
        if existing > asset.size:
            partial_path.unlink()
            existing = 0
        if existing == asset.size:
            if file_sha256(partial_path) == asset.sha256:
                os.replace(partial_path, destination)
                progress(100, "下载及校验完成")
                return
            partial_path.unlink()
            existing = 0

        headers = {"User-Agent": "Echovault/0.3"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(asset.url, headers=headers)

        try:
            response = opener(request, timeout=60)
            status = getattr(response, "status", 200)
            resumed = existing > 0 and status == 206
            received = existing if resumed else 0
            mode = "ab" if resumed else "wb"
            started = time.monotonic()

            with response, open(partial_path, mode) as file_handle:
                while True:
                    if cancelled():
                        raise DownloadCancelled("下载已取消")
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    file_handle.write(chunk)
                    received += len(chunk)
                    if received > asset.size:
                        raise ModelDownloadError("服务器返回的数据大于 Release 资产大小")

                    elapsed = max(time.monotonic() - started, 0.001)
                    session_bytes = received - (existing if resumed else 0)
                    speed = session_bytes / elapsed
                    percent = min(99, int(received * 100 / asset.size))
                    done_mb = received / 1024 / 1024
                    total_mb = asset.size / 1024 / 1024
                    speed_text = (
                        f"{speed / 1024 / 1024:.1f} MB/s"
                        if speed >= 1024 * 1024
                        else f"{speed / 1024:.0f} KB/s"
                    )
                    progress(
                        percent,
                        f"GitHub Release | {done_mb:.1f}/{total_mb:.1f} MB | {speed_text}",
                    )

            if received != asset.size:
                raise ModelDownloadError(
                    f"下载不完整: {received / 1024 / 1024:.1f}/{asset.size / 1024 / 1024:.1f} MB"
                )

        except DownloadCancelled:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and partial_path.exists():
                partial_path.unlink()
            if attempt == max_attempts:
                raise ModelDownloadError(f"GitHub 下载失败: HTTP {exc.code}") from exc
            wait = 2 ** (attempt - 1)
            progress(0, f"连接中断，{wait} 秒后重试 ({attempt + 1}/{max_attempts})...")
            sleeper(wait)
            continue
        except (OSError, TimeoutError, ModelDownloadError) as exc:
            if attempt == max_attempts:
                raise ModelDownloadError(f"GitHub 下载失败: {exc}") from exc
            wait = 2 ** (attempt - 1)
            progress(0, f"连接中断，{wait} 秒后重试 ({attempt + 1}/{max_attempts})...")
            sleeper(wait)
            continue

        progress(99, "正在进行 SHA-256 校验...")
        if file_sha256(partial_path) != asset.sha256:
            partial_path.unlink(missing_ok=True)
            raise ModelDownloadError("模型 SHA-256 校验失败，损坏文件已删除")
        os.replace(partial_path, destination)
        progress(100, "下载及校验完成")
        return

    raise ModelDownloadError("模型下载失败")
