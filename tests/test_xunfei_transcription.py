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
