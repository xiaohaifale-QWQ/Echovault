"""Runtime environment diagnostics for the GUI and CLI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from core.audio_utils import find_ffmpeg

BASE_PACKAGES = {
    "PyQt6": "PyQt6",
    "pydub": "pydub",
    "mutagen": "mutagen",
    "aiohttp": "aiohttp",
    "cryptography": "cryptography",
    "zeroconf": "zeroconf",
}


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def build_environment_report(config, cache_root: str | Path | None = None) -> dict:
    """Return a serializable report for the currently selected ASR provider."""
    packages = {name: _module_available(module) for name, module in BASE_PACKAGES.items()}
    ffmpeg_path = find_ffmpeg()
    provider = config.asr.provider
    cache = Path(cache_root) if cache_root else Path.home() / ".cache" / "whisper"

    if provider == "groq":
        provider_details = {
            "name": "groq",
            "sdk_installed": _module_available("groq"),
            "api_key_configured": bool(config.groq_api_key),
        }
        provider_ready = (
            provider_details["sdk_installed"] and provider_details["api_key_configured"]
        )
    elif provider == "local":
        model_path = cache / f"{config.asr.local_model}.pt"
        provider_details = {
            "name": "local",
            "whisper_installed": _module_available("whisper"),
            "model": config.asr.local_model,
            "model_installed": model_path.is_file() and model_path.stat().st_size > 100_000,
            "model_path": str(model_path),
        }
        provider_ready = (
            provider_details["whisper_installed"] and provider_details["model_installed"]
        )
    elif provider == "xunfei":
        provider_details = {
            "name": "xunfei",
            "app_id_configured": bool(config.xunfei_app_id),
            "api_key_configured": bool(config.xunfei_api_key),
            "api_secret_configured": bool(config.xunfei_api_secret),
            "implementation_ready": True,
        }
        provider_ready = config.has_xunfei_credentials
    else:
        provider_details = {"name": provider, "supported": False}
        provider_ready = False

    issues = []
    missing_base = [name for name, available in packages.items() if not available]
    if missing_base:
        issues.append("缺少基础依赖: " + ", ".join(missing_base))
    if not ffmpeg_path:
        issues.append("未找到 ffmpeg，请安装后加入 PATH")
    if not provider_ready:
        issues.append(f"当前识别引擎不可用: {provider}")

    return {
        "python": sys.version.split()[0],
        "packages": packages,
        "ffmpeg": {"available": bool(ffmpeg_path), "path": ffmpeg_path},
        "provider": provider_details,
        "ready_for_transcription": bool(ffmpeg_path) and provider_ready,
        "issues": issues,
    }
