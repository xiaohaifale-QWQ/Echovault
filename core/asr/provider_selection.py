"""Provider choice rules shared by interactive ASR features."""

from __future__ import annotations

from typing import Iterable


VOICE_INPUT_PRIORITY = ("groq", "xunfei", "local")


def select_available_provider(router, priority: Iterable[str] = VOICE_INPUT_PRIORITY) -> str:
    """Return the first configured and available provider from a priority list."""
    for provider_name in priority:
        provider = router.get(provider_name)
        if provider is not None and provider.is_available():
            return provider_name
    raise RuntimeError("没有可用的语音识别引擎。请配置在线引擎或下载本地模型。")
