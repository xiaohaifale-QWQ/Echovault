import json

import pytest

from core.asr.xunfei_transcription import XunfeiTranscriptionProvider


def test_xunfei_requires_all_three_credentials():
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
