"""UVR-backed denoise and de-reverb processing for separated vocal tracks."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio_utils import find_ffmpeg
from .vocal_separation import SeparationCancelled, SeparationError


@dataclass(frozen=True)
class EnhancementModel:
    key: str
    name: str
    description: str
    speed: str
    quality: str
    approximate_size: str
    filename: str
    target_stem: str
    expected_md5: str


MODEL_RELEASE_ROOT = (
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models"
)
ENHANCEMENT_MODELS = {
    "denoise": EnhancementModel(
        "denoise",
        "UVR DeNoise Lite",
        "去除分离后人声中的底噪、风噪和持续噪声",
        "较快",
        "高",
        "约 18 MB",
        "UVR-DeNoise-Lite.pth",
        "No Noise",
        "8e6bb148655d72cf832cd1e74cb57fb3",
    ),
    "dereverb": EnhancementModel(
        "dereverb",
        "UVR DeEcho-DeReverb",
        "抑制分离后人声中的回声、房间混响和拖尾",
        "中等",
        "高",
        "约 224 MB",
        "UVR-DeEcho-DeReverb.pth",
        "No Reverb",
        "27ad7622a9762fc83b6c606b89cfac47",
    ),
}

_METADATA_FILES = {
    "download_checks.json": (
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/"
        "filelists/download_checks.json"
    ),
    "vr_model_data.json": (
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/"
        "vr_model_data/model_data_new.json"
    ),
    "mdx_model_data.json": (
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/"
        "mdx_model_data/model_data_new.json"
    ),
}

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


def enhancement_cache_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    return root / "Echovault" / "models" / "enhancement"


def enhancement_available() -> bool:
    try:
        import audio_separator  # noqa: F401
        import librosa  # noqa: F401
        import soundfile  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def enhancement_model_installed(model: str) -> bool:
    spec = ENHANCEMENT_MODELS.get(model)
    if spec is None:
        return False
    cache = enhancement_cache_dir()
    checkpoint = cache / spec.filename
    return (
        checkpoint.is_file()
        and _md5(checkpoint) == spec.expected_md5
        and all((cache / filename).is_file() for filename in _METADATA_FILES)
    )


def _download(
    url: str,
    destination: Path,
    *,
    start_percent: int,
    end_percent: int,
    label: str,
    progress: ProgressCallback,
    cancelled: CancelCallback,
    opener,
) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with opener(url) as response, temporary.open("wb") as handle:
            total = int(response.headers.get("Content-Length", "0") or 0)
            received = 0
            while True:
                if cancelled():
                    raise SeparationCancelled("增强模型下载已取消")
                block = response.read(1024 * 1024)
                if not block:
                    break
                handle.write(block)
                received += len(block)
                ratio = received / total if total else 0.0
                percent = start_percent + int((end_percent - start_percent) * ratio)
                progress(min(end_percent, percent), f"正在下载{label}…")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def download_enhancement_model(
    model: str,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    opener=urllib.request.urlopen,
) -> Path:
    spec = ENHANCEMENT_MODELS.get(model)
    if spec is None:
        raise SeparationError(f"不支持的增强模型：{model}")
    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    cache = enhancement_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    checkpoint = cache / spec.filename

    if not checkpoint.is_file() or _md5(checkpoint) != spec.expected_md5:
        _download(
            f"{MODEL_RELEASE_ROOT}/{spec.filename}",
            checkpoint,
            start_percent=0,
            end_percent=94,
            label=spec.name,
            progress=progress,
            cancelled=cancelled,
            opener=opener,
        )
    if _md5(checkpoint) != spec.expected_md5:
        checkpoint.unlink(missing_ok=True)
        raise SeparationError(f"增强模型校验失败：{spec.filename}")

    metadata_items = list(_METADATA_FILES.items())
    for index, (filename, url) in enumerate(metadata_items):
        destination = cache / filename
        if destination.is_file():
            continue
        start = 94 + index * 2
        _download(
            url,
            destination,
            start_percent=start,
            end_percent=min(99, start + 2),
            label="UVR 模型配置",
            progress=progress,
            cancelled=cancelled,
            opener=opener,
        )
    progress(100, f"{spec.name} 安装完成")
    return checkpoint


def enhance_audio(
    source_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    model: str,
    device: str = "cpu",
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> Path:
    """Run one installed UVR enhancement model and atomically write its clean stem."""

    spec = ENHANCEMENT_MODELS.get(model)
    if spec is None:
        raise SeparationError(f"不支持的增强模型：{model}")
    if not enhancement_available():
        raise SeparationError("音频增强运行时未安装，请安装 audio-separator[cpu]")
    if not enhancement_model_installed(model):
        raise SeparationError(f"{spec.name} 尚未安装，请先在模型库下载")
    source = Path(source_path)
    output = Path(output_path)
    if not source.is_file():
        raise SeparationError(f"增强源音轨不存在：{source}")
    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise SeparationCancelled("音频增强已取消")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SeparationError("未找到 ffmpeg，无法执行音频增强")
    cache = enhancement_cache_dir()
    temporary_dir = Path(tempfile.mkdtemp(prefix="echovault_enhance_"))
    old_model_dir = os.environ.get("AUDIO_SEPARATOR_MODEL_DIR")
    old_path = os.environ.get("PATH", "")
    os.environ["AUDIO_SEPARATOR_MODEL_DIR"] = str(cache)
    os.environ["PATH"] = f"{Path(ffmpeg).resolve().parent}{os.pathsep}{old_path}"
    try:
        progress(5, f"正在加载 {spec.name}…")
        from audio_separator.separator import Separator

        separator = Separator(
            log_level=logging.WARNING,
            model_file_dir=str(cache),
            output_dir=str(temporary_dir),
            output_format="WAV",
            output_single_stem=spec.target_stem,
            use_autocast=device == "cuda",
            vr_params={
                "batch_size": 1,
                "window_size": 512,
                "aggression": 5,
                "enable_tta": False,
                "enable_post_process": False,
                "post_process_threshold": 0.2,
                "high_end_process": False,
            },
        )
        if device == "cpu":
            import torch

            separator.torch_device = torch.device("cpu")
            separator.torch_device_cpu = torch.device("cpu")
            separator.onnx_execution_provider = ["CPUExecutionProvider"]
        separator.load_model(spec.filename)
        if cancelled():
            raise SeparationCancelled("音频增强已取消")
        progress(20, f"正在执行 {spec.name}…")
        output_name = f"{source.stem}_{model}_clean"
        files = separator.separate(
            str(source), custom_output_names={spec.target_stem: output_name}
        )
        if cancelled():
            raise SeparationCancelled("音频增强已取消")
        if not files:
            raise SeparationError(f"{spec.name} 没有生成清洁音轨")
        rendered = Path(files[0])
        if not rendered.is_absolute():
            rendered = temporary_dir / rendered
        if not rendered.is_file():
            raise SeparationError(f"{spec.name} 输出文件不存在：{rendered.name}")
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = output.with_name(f".{output.stem}.{model}.tmp{output.suffix}")
        shutil.copyfile(rendered, staging)
        os.replace(staging, output)
        progress(100, f"{spec.name} 处理完成")
        return output
    except (SeparationCancelled, SeparationError):
        raise
    except Exception as exc:
        raise SeparationError(f"{spec.name} 处理失败：{exc}") from exc
    finally:
        if old_model_dir is None:
            os.environ.pop("AUDIO_SEPARATOR_MODEL_DIR", None)
        else:
            os.environ["AUDIO_SEPARATOR_MODEL_DIR"] = old_model_dir
        os.environ["PATH"] = old_path
        shutil.rmtree(temporary_dir, ignore_errors=True)
