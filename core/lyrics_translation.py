"""Timestamp-preserving LRC translation through AI or Argos Translate."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from core.ai_assistant import AISettings, complete

_TIMED_LINE = re.compile(
    r"^(?P<prefix>(?:\[\d{1,3}:\d{2}(?:\.\d{2,3})?\])+)(?P<text>.*)$"
)
LANGUAGE_NAMES = {
    "auto": "自动检测的源语言",
    "zh": "简体中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "es": "西班牙语",
    "fr": "法语",
    "de": "德语",
    "ru": "俄语",
}
logging.getLogger("argostranslate").setLevel(logging.WARNING)


def detect_lyrics_language(lines: Sequence[str]) -> str:
    """Detect the supported source language from lyric writing systems."""
    text = "\n".join(lines)
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    raise RuntimeError("无法自动检测歌词语言，请手工选择源语言。")


def translation_output_path(lrc_path: str | Path, target_language: str) -> Path:
    source = Path(lrc_path)
    return source.with_suffix(f".{target_language}.lrc")


def timed_text_positions(content: str) -> tuple[list[str], list[int], list[str]]:
    raw_lines = content.splitlines()
    positions: list[int] = []
    texts: list[str] = []
    for index, raw_line in enumerate(raw_lines):
        match = _TIMED_LINE.match(raw_line)
        if match and match.group("text").strip():
            positions.append(index)
            texts.append(match.group("text").strip())
    return raw_lines, positions, texts


def _decode_translation_response(response: str, expected_count: int) -> list[str]:
    start = response.find("{")
    end = response.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("AI 翻译没有返回 JSON 对象。")
    try:
        payload = json.loads(response[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI 翻译返回了无效 JSON。") from exc
    translations = payload.get("translations") if isinstance(payload, dict) else None
    if (
        not isinstance(translations, list)
        or len(translations) != expected_count
        or not all(isinstance(item, str) for item in translations)
    ):
        raise RuntimeError("AI 翻译返回的行数与原歌词不一致，未写入文件。")
    return [item.strip() for item in translations]


def translate_lines_with_ai(
    lines: Sequence[str],
    *,
    settings: AISettings,
    source_language: str,
    target_language: str,
    chunk_size: int = 40,
) -> list[str]:
    translated: list[str] = []
    source_name = LANGUAGE_NAMES.get(source_language, source_language)
    target_name = LANGUAGE_NAMES.get(target_language, target_language)
    for start in range(0, len(lines), chunk_size):
        chunk = list(lines[start : start + chunk_size])
        numbered = [{"index": index, "text": text} for index, text in enumerate(chunk)]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是歌词翻译器。只翻译文字，不添加解释，不合并或拆分行。"
                    "严格返回 JSON：{\"translations\":[\"第1行\",\"第2行\"]}，"
                    "数组长度必须与输入完全相同。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"把以下歌词从{source_name}翻译为{target_name}，保留专有名词和歌词语气：\n"
                    + json.dumps(numbered, ensure_ascii=False)
                ),
            },
        ]
        response = complete(settings, messages, temperature=0.1)
        translated.extend(_decode_translation_response(response, len(chunk)))
    return translated


def translate_lines_locally(
    lines: Sequence[str], *, source_language: str, target_language: str
) -> list[str]:
    if source_language == "auto":
        source_language = detect_lyrics_language(lines)
    if source_language == target_language:
        return list(lines)
    try:
        import argostranslate.translate
    except ImportError as exc:
        raise RuntimeError(
            "未安装本地翻译组件。请重新安装最新版 Echovault，或安装 requirements-translation.txt。"
        ) from exc
    if not local_translation_available(source_language, target_language):
        raise RuntimeError(
            f"尚未安装 {source_language} → {target_language} 本地翻译库，"
            "请在“设置 → 歌词输出”中下载。"
        )
    cache: dict[str, str] = {}
    translated = []
    for line in lines:
        if line not in cache:
            cache[line] = argostranslate.translate.translate(
                line, source_language, target_language
            ).strip()
        translated.append(cache[line])
    return translated


def local_translation_available(source_language: str, target_language: str) -> bool:
    try:
        import argostranslate.translate
    except ImportError:
        return False
    installed = argostranslate.translate.get_installed_languages()
    source = next((item for item in installed if item.code == source_language), None)
    target = next((item for item in installed if item.code == target_language), None)
    if source is None or target is None:
        return False
    try:
        translation = source.get_translation(target)
    except (AttributeError, RuntimeError):
        return False
    return translation is not None


def install_local_translation_package(source_language: str, target_language: str) -> str:
    if source_language == target_language:
        raise RuntimeError("源语言和目标语言不能相同。")
    try:
        import argostranslate.package
    except ImportError as exc:
        raise RuntimeError(
            "未安装本地翻译组件。请重新安装最新版 Echovault，或安装 requirements-translation.txt。"
        ) from exc
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    package = next(
        (
            item
            for item in available
            if item.from_code == source_language and item.to_code == target_language
        ),
        None,
    )
    if package is None:
        raise RuntimeError(f"Argos 软件包索引中没有 {source_language} → {target_language} 模型。")
    package_path = package.download()
    argostranslate.package.install_from_path(package_path)
    return f"{source_language} → {target_language} 本地翻译库已安装"


def translate_lrc_file(
    lrc_path: str | Path,
    *,
    engine: str,
    source_language: str,
    target_language: str,
    ai_settings: AISettings | None = None,
    output_path: str | Path | None = None,
    translator: Callable[[Sequence[str]], Sequence[str]] | None = None,
) -> Path:
    source = Path(lrc_path)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if source_language == target_language:
        raise RuntimeError("源语言和目标语言不能相同。")
    content = source.read_text(encoding="utf-8")
    raw_lines, positions, texts = timed_text_positions(content)
    if not texts:
        raise RuntimeError(f"LRC 中没有可翻译的时间轴歌词：{source}")
    if translator is not None:
        translations = list(translator(texts))
    elif engine == "local":
        translations = translate_lines_locally(
            texts,
            source_language=source_language,
            target_language=target_language,
        )
    elif engine == "ai":
        if ai_settings is None:
            raise RuntimeError("AI 翻译缺少接口配置。")
        translations = translate_lines_with_ai(
            texts,
            settings=ai_settings,
            source_language=source_language,
            target_language=target_language,
        )
    else:
        raise RuntimeError(f"不支持的翻译引擎：{engine}")
    if len(translations) != len(positions):
        raise RuntimeError("译文行数与原歌词不一致，未写入文件。")
    for line_index, translated_text in zip(positions, translations):
        match = _TIMED_LINE.match(raw_lines[line_index])
        raw_lines[line_index] = match.group("prefix") + str(translated_text).strip()
    destination = (
        Path(output_path)
        if output_path
        else translation_output_path(source, target_language)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(raw_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)
    from core.transfer_session import register_artifact

    register_artifact(source, destination, "translation")
    return destination
