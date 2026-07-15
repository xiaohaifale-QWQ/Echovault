import json
import sys
from types import ModuleType

import pytest

from core.ai_assistant import AISettings
from core.lyrics_translation import (
    _decode_translation_response,
    detect_lyrics_language,
    local_translation_available,
    translate_lines_locally,
    translate_lines_with_ai,
    translate_lrc_file,
    translation_output_path,
)


def test_translation_output_path_adds_language_suffix(tmp_path):
    assert translation_output_path(tmp_path / "song.lrc", "zh") == tmp_path / "song.zh.lrc"


def test_translate_lrc_preserves_exact_timestamp_prefix_and_original(tmp_path):
    source = tmp_path / "song.lrc"
    original = "[ti:Song]\n[00:01.230]Hello\n[00:04.50][00:08.50]World\n"
    source.write_text(original, encoding="utf-8")

    output = translate_lrc_file(
        source,
        engine="local",
        source_language="en",
        target_language="zh",
        translator=lambda lines: ["你好", "世界"],
    )

    assert source.read_text(encoding="utf-8") == original
    assert output.name == "song.zh.lrc"
    assert output.read_text(encoding="utf-8") == (
        "[ti:Song]\n[00:01.230]你好\n[00:04.50][00:08.50]世界\n"
    )


def test_translate_lrc_does_not_write_on_line_count_mismatch(tmp_path):
    source = tmp_path / "song.lrc"
    source.write_text("[00:01.00]Hello\n[00:02.00]World", encoding="utf-8")

    with pytest.raises(RuntimeError, match="行数"):
        translate_lrc_file(
            source,
            engine="local",
            source_language="en",
            target_language="zh",
            translator=lambda _lines: ["只有一行"],
        )

    assert not (tmp_path / "song.zh.lrc").exists()


def test_decode_translation_response_accepts_markdown_wrapped_json():
    result = _decode_translation_response(
        '```json\n{"translations":["你好","世界"]}\n```', 2
    )

    assert result == ["你好", "世界"]


def test_decode_translation_response_rejects_wrong_line_count():
    with pytest.raises(RuntimeError, match="行数"):
        _decode_translation_response('{"translations":["你好"]}', 2)


def test_ai_translation_sends_numbered_lines_and_preserves_count(monkeypatch):
    captured = {}

    def fake_complete(settings, messages, temperature):
        captured["messages"] = messages
        captured["temperature"] = temperature
        return json.dumps({"translations": ["你好", "世界"]}, ensure_ascii=False)

    monkeypatch.setattr("core.lyrics_translation.complete", fake_complete)

    result = translate_lines_with_ai(
        ["Hello", "World"],
        settings=AISettings(api_key="secret"),
        source_language="en",
        target_language="zh",
    )

    assert result == ["你好", "世界"]
    assert '"index": 0' in captured["messages"][1]["content"]
    assert captured["temperature"] == 0.1


def test_local_translation_status_requires_an_actual_translation(monkeypatch):
    class Language:
        def __init__(self, code, translation=None):
            self.code = code
            self.translation = translation

        def get_translation(self, _target):
            return self.translation

    source = Language("en")
    target = Language("zh")
    translate_module = ModuleType("argostranslate.translate")
    translate_module.get_installed_languages = lambda: [source, target]
    package_module = ModuleType("argostranslate")
    package_module.translate = translate_module
    monkeypatch.setitem(sys.modules, "argostranslate", package_module)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", translate_module)

    assert local_translation_available("en", "zh") is False
    source.translation = object()
    assert local_translation_available("en", "zh") is True


@pytest.mark.parametrize(
    ("lyrics", "expected"),
    [
        (["Hello world"], "en"),
        (["繁體歌詞"], "zh"),
        (["夢を見ている"], "ja"),
        (["사랑해"], "ko"),
    ],
)
def test_detect_lyrics_language_by_writing_system(lyrics, expected):
    assert detect_lyrics_language(lyrics) == expected


def test_ai_translation_prompt_requests_automatic_source_detection(monkeypatch):
    captured = {}

    def fake_complete(_settings, messages, temperature):
        captured["prompt"] = messages[1]["content"]
        return '{"translations":["你好"]}'

    monkeypatch.setattr("core.lyrics_translation.complete", fake_complete)

    translate_lines_with_ai(
        ["Hello"],
        settings=AISettings(api_key="secret"),
        source_language="auto",
        target_language="zh",
    )

    assert "自动检测" in captured["prompt"]


def test_local_auto_detection_skips_translation_when_already_target_language():
    assert translate_lines_locally(
        ["已经是中文"], source_language="auto", target_language="zh"
    ) == ["已经是中文"]
