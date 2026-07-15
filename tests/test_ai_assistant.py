import pytest

from core.ai_assistant import SYSTEM_PROMPT, AISettings, build_messages, chat, settings_from_config
from core.config import AppConfig


def test_assistant_always_includes_product_manual_and_prompt():
    messages = build_messages("介绍这个软件", [{"role": "user", "content": "之前的问题"}])

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "素材库" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "介绍这个软件"}


def test_online_assistant_requires_api_key():
    with pytest.raises(RuntimeError, match="API Key"):
        chat(AISettings(api_key=""), "你好")


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"choices":[{"message":{"content":"ok"}}]}'


def test_local_openai_compatible_endpoint_allows_an_empty_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("core.ai_assistant.urllib.request.urlopen", fake_urlopen)
    config = AppConfig(
        ai_provider="local",
        local_ai_base_url="http://127.0.0.1:11434/v1/",
        local_ai_model_name="qwen3:8b",
    )

    result = chat(settings_from_config(config), "你好")

    assert result == "ok"
    assert captured["request"].full_url == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["request"].get_header("Authorization") is None
    assert captured["timeout"] == 60


def test_local_endpoint_sends_optional_bearer_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        return _Response()

    monkeypatch.setattr("core.ai_assistant.urllib.request.urlopen", fake_urlopen)
    settings = AISettings(
        api_key="local-secret",
        base_url="http://127.0.0.1:1234/v1",
        model="loaded-model",
        provider_name="本地 AI",
        requires_api_key=False,
    )

    chat(settings, "你好")

    assert captured["authorization"] == "Bearer local-secret"
