from core.asr.base import Segment, TranscriptionResult
from core.lrc_writer import segments_to_lrc


def _result(text: str, language: str) -> TranscriptionResult:
    return TranscriptionResult(
        segments=[Segment(0.0, 2.0, text)],
        language=language,
        duration=2.0,
    )


def test_auto_detected_chinese_name_is_converted_to_simplified():
    result = _result("繁體歌詞：愛與夢", "Chinese")

    lrc = segments_to_lrc(result, post_process=False)

    assert lrc.lines[0].text == "繁体歌词：爱与梦"
    assert result.segments[0].text == "繁體歌詞：愛與夢"


def test_requested_chinese_language_overrides_unknown_detection():
    result = _result("音樂同步軟體與歌詞", "unknown")

    lrc = segments_to_lrc(result, post_process=False, language_hint="zh")

    assert lrc.lines[0].text == "音乐同步软体与歌词"


def test_traditional_chinese_locale_is_converted_to_simplified():
    result = _result("雲端資料與離線模型", "zh-TW")

    lrc = segments_to_lrc(result, post_process=False)

    assert lrc.lines[0].text == "云端资料与离线模型"


def test_leading_composer_hallucination_is_removed():
    result = TranscriptionResult(
        segments=[
            Segment(0.0, 1.0, "作曲"),
            Segment(1.0, 2.0, "李宗盛"),
            Segment(2.0, 5.0, "真正的歌词从这里开始"),
        ],
        language="zh",
        duration=5.0,
    )

    lrc = segments_to_lrc(result, post_process=False)

    assert [line.text for line in lrc.lines] == ["真正的歌词从这里开始"]


def test_complete_leading_credit_does_not_remove_first_lyric():
    result = TranscriptionResult(
        segments=[
            Segment(0.0, 1.0, "作曲：李宗盛"),
            Segment(1.0, 4.0, "这是应当保留的第一行歌词"),
        ],
        language="zh",
        duration=4.0,
    )

    lrc = segments_to_lrc(result, post_process=False)

    assert [line.text for line in lrc.lines] == ["这是应当保留的第一行歌词"]
