import pytest

from core.asr.provider_selection import select_available_provider


class _Provider:
    def __init__(self, available: bool):
        self._available = available

    def is_available(self):
        return self._available


class _Router:
    def __init__(self, providers):
        self.providers = providers

    def get(self, name):
        return self.providers.get(name)


def test_voice_input_prefers_online_provider_before_local():
    router = _Router({"groq": _Provider(True), "xunfei": _Provider(True), "local": _Provider(True)})

    assert select_available_provider(router) == "groq"


def test_voice_input_uses_xunfei_then_local_when_higher_priority_unavailable():
    router = _Router({"groq": _Provider(False), "xunfei": _Provider(True), "local": _Provider(True)})
    assert select_available_provider(router) == "xunfei"

    router = _Router({"groq": _Provider(False), "xunfei": _Provider(False), "local": _Provider(True)})
    assert select_available_provider(router) == "local"


def test_voice_input_requires_any_available_provider():
    router = _Router({"groq": _Provider(False), "xunfei": _Provider(False), "local": _Provider(False)})

    with pytest.raises(RuntimeError, match="没有可用"):
        select_available_provider(router)
