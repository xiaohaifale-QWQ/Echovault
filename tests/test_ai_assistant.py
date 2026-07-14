import pytest

from core.ai_assistant import SYSTEM_PROMPT, AISettings, build_messages, chat


def test_assistant_always_includes_product_manual_and_prompt():
    messages = build_messages("介绍这个软件", [{"role": "user", "content": "之前的问题"}])

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "素材库" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "介绍这个软件"}


def test_assistant_requires_local_deepseek_key():
    with pytest.raises(RuntimeError, match="DeepSeek API Key"):
        chat(AISettings(api_key=""), "你好")
