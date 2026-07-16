from core.config import AppConfig
from core.environment import build_environment_report


def test_report_explains_missing_ffmpeg_and_groq(monkeypatch, tmp_path):
    config = AppConfig()
    config.asr.provider = "groq"
    config.groq_api_key = ""
    monkeypatch.setattr("core.environment.find_ffmpeg", lambda: None)
    monkeypatch.setattr("core.environment._module_available", lambda name: name != "groq")

    report = build_environment_report(config, cache_root=tmp_path)

    assert report["ready_for_transcription"] is False
    assert report["ffmpeg"]["available"] is False
    assert any("ffmpeg" in issue for issue in report["issues"])
    assert report["provider"]["api_key_configured"] is False


def test_local_provider_requires_model_file(monkeypatch, tmp_path):
    config = AppConfig()
    config.asr.provider = "local"
    config.asr.local_model = "tiny"
    monkeypatch.setattr("core.environment.find_ffmpeg", lambda: "C:/ffmpeg.exe")
    monkeypatch.setattr("core.environment._module_available", lambda _name: True)

    missing = build_environment_report(config, cache_root=tmp_path)
    assert missing["ready_for_transcription"] is False

    model = tmp_path / "tiny.pt"
    model.write_bytes(b"x" * 100_001)
    ready = build_environment_report(config, cache_root=tmp_path)
    assert ready["ready_for_transcription"] is True


def test_xunfei_provider_requires_http_and_websocket_clients(monkeypatch, tmp_path):
    config = AppConfig()
    config.asr.provider = "xunfei"
    config.xunfei_app_id = "app"
    config.xunfei_api_key = "key"
    config.xunfei_api_secret = "secret"
    monkeypatch.setattr("core.environment.find_ffmpeg", lambda: "C:/ffmpeg.exe")
    monkeypatch.setattr(
        "core.environment._module_available",
        lambda name: name != "websocket",
    )

    report = build_environment_report(config, cache_root=tmp_path)

    assert report["ready_for_transcription"] is False
    assert report["provider"]["requests_installed"] is True
    assert report["provider"]["websocket_installed"] is False
