import json
from urllib.parse import parse_qs, urlparse

import pytest

from core.asr.base import Segment, TranscriptionResult
from core.asr.xunfei_transcription import (
    XunfeiAPIError,
    XunfeiTranscriptionProvider,
)


def test_xunfei_requires_all_three_credentials(monkeypatch):
    monkeypatch.delenv("XUNFEI_APP_ID", raising=False)
    monkeypatch.delenv("XUNFEI_API_KEY", raising=False)
    monkeypatch.delenv("XUNFEI_API_SECRET", raising=False)
    assert not XunfeiTranscriptionProvider(app_id="app", api_key="key").is_available()
    assert XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    ).is_available()


def test_xunfei_parses_timestamped_lattice_result():
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )
    result = provider._parse_result(
        {
            "lattice": [
                {
                    "json_1best": {
                        "st": {
                            "bg": "1200",
                            "ed": "3600",
                            "sc": "0.95",
                            "rt": [
                                {
                                    "ws": [
                                        {"cw": [{"w": "你好"}]},
                                        {"cw": [{"w": "世界"}]},
                                    ]
                                }
                            ],
                        }
                    }
                }
            ]
        },
        "zh",
        4.0,
    )

    assert result.language == "zh"
    assert result.duration == 4.0
    assert result.full_text == "你好世界"
    assert result.segments[0].start_time == 1.2
    assert result.segments[0].end_time == 3.6


def test_xunfei_multipart_body_contains_credentials_and_audio():
    body, boundary = XunfeiTranscriptionProvider._multipart_body(
        {"app_id": "app", "request_id": "request"},
        "sample.wav",
        b"audio-data",
        "audio/wav",
    )

    assert boundary.encode() in body
    assert b'name="app_id"' in body
    assert b"audio-data" in body
    assert b'filename="sample.wav"' in body


@pytest.mark.parametrize(
    ("language", "expected_type"),
    [(None, 1), ("zh", 2), ("en", 3)],
)
def test_xunfei_uses_documented_zh_cn_language_modes(language, expected_type, monkeypatch):
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )
    captured = {}

    def fake_post_json(_url, payload):
        captured["payload"] = payload
        return {"data": {"task_id": "task"}}

    monkeypatch.setattr(provider, "_post_json", fake_post_json)

    assert provider._create_task("https://audio.invalid", 10, language, 1.2) == "task"
    assert captured["payload"]["business"]["language"] == "zh_cn"
    assert captured["payload"]["business"]["language_type"] == expected_type


def test_xunfei_rejects_unsupported_language_before_upload(tmp_path, monkeypatch):
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not-uploaded")
    monkeypatch.setattr(provider, "_upload_file", lambda _path: pytest.fail("must not upload"))

    with pytest.raises(RuntimeError, match="仅支持中文、英文"):
        provider.transcribe(str(audio), language="ja")


def test_xunfei_accepts_json_string_result(monkeypatch):
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )
    expected = {"lattice": []}
    monkeypatch.setattr(
        provider,
        "_post_json",
        lambda *_args: {
            "data": {"task_status": "3", "result": json.dumps(expected)}
        },
    )

    assert provider._wait_for_result("task", 1.0) == expected


def test_xunfei_license_error_has_actionable_message():
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )

    message = provider._response_error({"code": 11200, "message": "licc failed"}, 500)

    assert "未获授权" in message
    assert "同一 AppID" in message


def test_xunfei_falls_back_to_streaming_dictation_on_speed_license_error(
    monkeypatch, tmp_path
):
    source = tmp_path / "source.mp3"
    converted = tmp_path / "converted.wav"
    source.write_bytes(b"source")
    converted.write_bytes(b"converted")
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )
    expected = TranscriptionResult(
        segments=[Segment(1.0, 2.0, "流式听写成功")],
        language="zh",
        duration=3.0,
    )
    monkeypatch.setattr(
        "core.asr.xunfei_transcription.convert_to_whisper_format",
        lambda _path: str(converted),
    )
    monkeypatch.setattr(
        "core.asr.xunfei_transcription.get_audio_info",
        lambda _path: {"duration": 3.0},
    )
    monkeypatch.setattr(provider, "_upload_file", lambda _path: "https://audio")
    monkeypatch.setattr(
        provider,
        "_create_task",
        lambda *_args: (_ for _ in ()).throw(
            XunfeiAPIError(11200, "极速录音转写未获授权")
        ),
    )
    monkeypatch.setattr(
        provider,
        "_transcribe_streaming",
        lambda _path, _language, _duration: expected,
    )

    result = provider.transcribe(str(source), "zh")

    assert result is expected
    assert provider._speed_transcription_available is False
    assert not converted.exists()


def test_xunfei_streaming_auth_url_contains_signed_query():
    provider = XunfeiTranscriptionProvider(
        app_id="app", api_key="key", api_secret="secret"
    )

    parsed = urlparse(provider._streaming_auth_url())
    query = parse_qs(parsed.query)

    assert parsed.scheme == "wss"
    assert parsed.netloc == "iat-api.xfyun.cn"
    assert query["host"] == ["iat-api.xfyun.cn"]
    assert query["date"]
    assert query["authorization"]


def test_xunfei_parses_streaming_text_and_vad_timestamps():
    packets = [
        {
            "code": 0,
            "data": {
                "status": 2,
                "result": {
                    "ws": [
                        {"cw": [{"w": "你好", "sc": 0.9}]},
                        {"cw": [{"w": "世界", "sc": 0.8}]},
                    ],
                    "vad": {"ws": [{"bg": 120, "ed": 360}]},
                },
            },
        }
    ]

    segments = XunfeiTranscriptionProvider._parse_streaming_packets(
        packets,
        offset=50.0,
        chunk_duration=10.0,
    )

    assert len(segments) == 1
    assert segments[0].text == "你好世界"
    assert segments[0].start_time == pytest.approx(51.2)
    assert segments[0].end_time == pytest.approx(53.6)
    assert segments[0].confidence == pytest.approx(0.85)


def test_xunfei_attaches_streaming_punctuation_to_previous_segment():
    segments = [
        Segment(0.0, 1.0, "第一句"),
        Segment(1.0, 1.2, "，第二句"),
        Segment(2.0, 2.1, "。"),
    ]

    normalized = XunfeiTranscriptionProvider._normalize_streaming_segments(segments)

    assert [segment.text for segment in normalized] == ["第一句，", "第二句。"]
    assert normalized[-1].end_time == 2.1
