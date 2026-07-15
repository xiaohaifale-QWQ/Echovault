"""Demucs-backed vocal/accompaniment separation and stem mixing."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio_utils import find_ffmpeg
from .process_utils import hidden_window_kwargs


class SeparationError(RuntimeError):
    """Raised when a separation or stem export cannot be completed."""


class SeparationCancelled(SeparationError):
    """Raised when the caller cancels download or processing."""


@dataclass(frozen=True)
class SeparationModel:
    key: str
    name: str
    description: str
    speed: str
    quality: str
    approximate_size: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class SeparationResult:
    vocals_path: Path | None
    accompaniment_path: Path | None
    sample_rate: int


REMOTE_ROOT = "https://dl.fbaipublicfiles.com/demucs"
SEPARATION_MODELS = {
    "htdemucs": SeparationModel(
        "htdemucs",
        "HTDemucs（推荐）",
        "通用人声/伴奏分离，质量与速度平衡",
        "中等",
        "高",
        "约 80 MB",
        ("hybrid_transformer/955717e8-8726e21a.th",),
    ),
    "htdemucs_ft": SeparationModel(
        "htdemucs_ft",
        "HTDemucs Fine-tuned",
        "四模型精调组合，细节更好但处理更慢",
        "较慢",
        "更高",
        "约 320 MB",
        (
            "hybrid_transformer/f7e0c4bc-ba3fe64a.th",
            "hybrid_transformer/d12395a8-e57c48e6.th",
            "hybrid_transformer/92cfc3b6-ef3bcb9c.th",
            "hybrid_transformer/04573f0d-f3cf25b2.th",
        ),
    ),
    "mdx_extra_q": SeparationModel(
        "mdx_extra_q",
        "MDX Extra Quantized",
        "量化轻量模型，下载较小、适合快速预览",
        "较快",
        "中等",
        "约 170 MB",
        (
            "mdx_final/83fc094f-4a16d450.th",
            "mdx_final/464b36d7-e5a9386e.th",
            "mdx_final/14fc6a69-a89dd0ee.th",
            "mdx_final/7fd6ef75-a905dd85.th",
        ),
    ),
}

MODEL_BAGS = {
    "htdemucs": "models: ['955717e8']\n",
    "htdemucs_ft": (
        "models: ['f7e0c4bc', 'd12395a8', '92cfc3b6', '04573f0d']\n"
        "weights:\n"
        "  - [1.0, 0.0, 0.0, 0.0]\n"
        "  - [0.0, 1.0, 0.0, 0.0]\n"
        "  - [0.0, 0.0, 1.0, 0.0]\n"
        "  - [0.0, 0.0, 0.0, 1.0]\n"
    ),
    "mdx_extra_q": (
        "models: ['83fc094f', '464b36d7', '14fc6a69', '7fd6ef75']\n"
        "segment: 44\n"
    ),
}

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


def separation_available() -> bool:
    try:
        import demucs.api  # noqa: F401
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def model_cache_dir() -> Path:
    try:
        import torch

        return Path(torch.hub.get_dir()) / "checkpoints"
    except (ImportError, OSError):
        return Path.home() / ".cache" / "torch" / "hub" / "checkpoints"


def _checkpoint_name(relative_path: str) -> str:
    return Path(relative_path).name


def _expected_hash_prefix(relative_path: str) -> str:
    return Path(relative_path).stem.rsplit("-", 1)[-1]


def _hash_matches(path: Path, expected_prefix: str) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().startswith(expected_prefix)


def separation_model_installed(model: str) -> bool:
    spec = SEPARATION_MODELS.get(model)
    if spec is None:
        return False
    cache_dir = model_cache_dir()
    return all(
        _hash_matches(cache_dir / _checkpoint_name(item), _expected_hash_prefix(item))
        for item in spec.files
    )


def _ensure_model_bag(cache_dir: Path, model: str) -> Path:
    """Create Demucs' small local bag manifest beside verified checkpoints."""

    content = MODEL_BAGS.get(model)
    if content is None:
        raise SeparationError(f"缺少人声分离模型清单：{model}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{model}.yaml"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return path
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return path


def download_separation_model(
    model: str,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    opener=urllib.request.urlopen,
) -> Path:
    """Download Demucs checkpoints into the cache used by ``torch.hub``."""

    spec = SEPARATION_MODELS.get(model)
    if spec is None:
        raise SeparationError(f"不支持的人声分离模型：{model}")
    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    cache_dir = model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    total_files = len(spec.files)

    for index, relative_path in enumerate(spec.files):
        if cancelled():
            raise SeparationCancelled("模型下载已取消")
        filename = _checkpoint_name(relative_path)
        destination = cache_dir / filename
        expected_hash = _expected_hash_prefix(relative_path)
        start_percent = index * 100 // total_files
        span = 100 // total_files
        if _hash_matches(destination, expected_hash):
            progress(start_percent + span, f"{filename} 已安装并通过校验")
            continue
        destination.unlink(missing_ok=True)
        partial = destination.with_suffix(destination.suffix + ".download")
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "Echovault/0.4"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(
            f"{REMOTE_ROOT}/{relative_path}", headers=headers
        )
        try:
            response = opener(request, timeout=60)
            status = getattr(response, "status", 200)
            resumed = bool(existing and status == 206)
            mode = "ab" if resumed else "wb"
            received = existing if resumed else 0
            header_length = int(response.headers.get("Content-Length", "0") or 0)
            total_bytes = received + header_length if resumed else header_length
            started = time.monotonic()
            with response, partial.open(mode) as output:
                while True:
                    if cancelled():
                        raise SeparationCancelled("模型下载已取消")
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    received += len(chunk)
                    ratio = received / total_bytes if total_bytes else 0
                    percent = start_percent + min(span - 1, int(ratio * span))
                    elapsed = max(time.monotonic() - started, 0.001)
                    speed = received / elapsed / 1024 / 1024
                    size_text = (
                        f"{received / 1024 / 1024:.1f}/{total_bytes / 1024 / 1024:.1f} MB"
                        if total_bytes
                        else f"{received / 1024 / 1024:.1f} MB"
                    )
                    progress(percent, f"{filename} | {size_text} | {speed:.1f} MB/s")
        except SeparationCancelled:
            raise
        except Exception as exc:
            raise SeparationError(f"模型下载失败：{exc}") from exc

        progress(start_percent + max(1, span - 1), f"正在校验 {filename}…")
        if not _hash_matches(partial, expected_hash):
            partial.unlink(missing_ok=True)
            raise SeparationError(f"{filename} SHA-256 校验失败，损坏文件已删除")
        os.replace(partial, destination)
        progress(start_percent + span, f"{filename} 下载完成")

    _ensure_model_bag(cache_dir, model)
    progress(100, f"{spec.name} 已安装")
    return cache_dir


def recommended_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except (ImportError, OSError):
        return "cpu"


def separate_vocals(
    input_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    model: str = "htdemucs",
    device: str = "cpu",
    output_content: str = "both",
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> SeparationResult:
    """Separate one media file into lossless vocal and accompaniment WAV files."""

    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    input_path = Path(input_path)
    if not input_path.is_file():
        raise SeparationError(f"素材不存在：{input_path}")
    if not separation_available():
        raise SeparationError("人声分离运行时未安装，请先安装 demucs、torch 和 torchaudio")
    if model not in SEPARATION_MODELS:
        raise SeparationError(f"不支持的人声分离模型：{model}")
    if output_content not in {"both", "vocals", "accompaniment"}:
        raise SeparationError(f"不支持的输出内容：{output_content}")
    if not separation_model_installed(model):
        raise SeparationError("所选人声分离模型尚未下载，请先打开模型库安装")
    if cancelled():
        raise SeparationCancelled("处理已取消")

    from demucs.api import Separator, save_audio

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    vocals_path = output_dir / f"{input_path.stem}_vocals.wav"
    accompaniment_path = output_dir / f"{input_path.stem}_accompaniment.wav"
    temporary_vocals = vocals_path.with_name(f".{vocals_path.stem}.tmp.wav")
    temporary_accompaniment = accompaniment_path.with_name(
        f".{accompaniment_path.stem}.tmp.wav"
    )

    def demucs_callback(event: dict) -> None:
        if cancelled():
            raise SeparationCancelled("处理已取消")
        audio_length = max(int(event.get("audio_length", 0)), 1)
        offset = max(int(event.get("segment_offset", 0)), 0)
        model_count = max(int(event.get("models", 1)), 1)
        model_index = max(int(event.get("model_idx_in_bag", 0)), 0)
        within_model = min(1.0, offset / audio_length)
        ratio = (model_index + within_model) / model_count
        progress(15 + int(70 * ratio), "正在分离人声与伴奏…")

    try:
        progress(2, "正在加载人声分离模型…")
        local_repo = model_cache_dir()
        _ensure_model_bag(local_repo, model)
        separator = Separator(
            model=model,
            repo=local_repo,
            device=device,
            shifts=1,
            overlap=0.25,
            split=True,
            progress=False,
            callback=demucs_callback,
        )
        progress(10, f"正在读取音频：{input_path.name}")
        origin, stems = separator.separate_audio_file(input_path)
        if "vocals" not in stems:
            raise SeparationError("模型输出中没有 vocals 音轨")
        vocals = stems["vocals"]
        accompaniment = origin - vocals
        saved_vocals = None
        saved_accompaniment = None
        if output_content in {"both", "vocals"}:
            progress(88, "正在写入人声音轨…")
            save_audio(vocals, temporary_vocals, separator.samplerate, bits_per_sample=24)
            os.replace(temporary_vocals, vocals_path)
            saved_vocals = vocals_path
        if output_content in {"both", "accompaniment"}:
            progress(94, "正在写入伴奏音轨…")
            save_audio(
                accompaniment,
                temporary_accompaniment,
                separator.samplerate,
                bits_per_sample=24,
            )
            os.replace(temporary_accompaniment, accompaniment_path)
            saved_accompaniment = accompaniment_path
        progress(100, "人声与伴奏分离完成")
        return SeparationResult(saved_vocals, saved_accompaniment, separator.samplerate)
    except SeparationCancelled:
        raise
    except Exception as exc:
        if isinstance(exc, SeparationError):
            raise
        raise SeparationError(f"人声分离失败：{exc}") from exc
    finally:
        temporary_vocals.unlink(missing_ok=True)
        temporary_accompaniment.unlink(missing_ok=True)


def mix_stems(
    vocals_path: str | os.PathLike[str],
    accompaniment_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    vocal_volume: int = 100,
    accompaniment_volume: int = 100,
) -> Path:
    """Render the two preview tracks with their selected gains."""

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SeparationError("未找到 ffmpeg，无法保存调音结果")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f"{output_path.stem}.rendering{output_path.suffix}")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(accompaniment_path),
        "-i",
        str(vocals_path),
        "-filter_complex",
        (
            f"[0:a]volume={accompaniment_volume / 100:.3f}[a];"
            f"[1:a]volume={vocal_volume / 100:.3f}[v];"
            "[a][v]amix=inputs=2:duration=longest:normalize=0[out]"
        ),
        "-map",
        "[out]",
        str(temp_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            **hidden_window_kwargs(),
        )
        os.replace(temp_path, output_path)
    except subprocess.CalledProcessError as exc:
        raise SeparationError(f"保存调音结果失败：{exc.stderr[-500:]}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return output_path
