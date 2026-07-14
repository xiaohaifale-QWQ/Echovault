import json

import pytest

from core.config import CONFIG_SCHEMA_VERSION, AppConfig, ConfigManager, update_config_value


def test_config_roundtrip_persists_api_keys(tmp_path):
    path = tmp_path / "config.json"
    manager = ConfigManager(path)
    manager.config.groq_api_key = "groq-secret"
    manager.config.groq_proxy_url = "http://127.0.0.1:7890"
    manager.config.xunfei_app_id = "xunfei-app-id"
    manager.config.xunfei_api_key = "xunfei-secret"
    manager.config.xunfei_api_secret = "xunfei-api-secret"
    manager.config.ai_model_api_key = "ai-secret"
    manager.config.ai_base_url = "https://example.invalid"
    manager.config.ai_model_name = "test-model"
    manager.config.voice_input_shortcut = "Ctrl+Alt+V"
    manager.config.music_dirs = ["D:/Music"]
    manager.config.video_dirs = ["D:/Video"]
    manager.config.music_select_all = True
    manager.config.video_select_all = True
    manager.config.video_time_offsets = {"D:/Video": 120}

    manager.save()
    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "groq-secret"
    assert loaded.groq_proxy_url == "http://127.0.0.1:7890"
    assert loaded.xunfei_app_id == "xunfei-app-id"
    assert loaded.xunfei_api_key == "xunfei-secret"
    assert loaded.xunfei_api_secret == "xunfei-api-secret"
    assert loaded.has_xunfei_credentials is True
    assert loaded.ai_model_api_key == "ai-secret"
    assert loaded.ai_base_url == "https://example.invalid"
    assert loaded.ai_model_name == "test-model"
    assert loaded.voice_input_shortcut == "Ctrl+Alt+V"
    assert loaded.music_dirs == ["D:/Music"]
    assert loaded.video_dirs == ["D:/Video"]
    assert loaded.music_select_all is True
    assert loaded.video_select_all is True
    assert loaded.video_time_offsets == {"D:/Video": 120}

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == CONFIG_SCHEMA_VERSION
    assert not path.with_suffix(".json.tmp").exists()


def test_environment_api_key_takes_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({
            "groq_api_key": "file-secret",
            "xunfei_app_id": "file-app-id",
            "xunfei_api_key": "file-xunfei",
            "xunfei_api_secret": "file-api-secret",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_API_KEY", "environment-secret")
    monkeypatch.setenv("XUNFEI_APP_ID", "environment-app-id")
    monkeypatch.setenv("XUNFEI_API_KEY", "environment-xunfei")
    monkeypatch.setenv("XUNFEI_API_SECRET", "environment-api-secret")

    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "environment-secret"
    assert loaded.xunfei_app_id == "environment-app-id"
    assert loaded.xunfei_api_key == "environment-xunfei"
    assert loaded.xunfei_api_secret == "environment-api-secret"


def test_update_config_value_validates_provider_and_booleans():
    config = AppConfig()

    update_config_value(config, "asr.provider", "local")
    update_config_value(config, "asr.use_gpu", "yes")
    update_config_value(config, "asr.language", "auto")
    update_config_value(config, "ai_model_api_key", "local-only-secret")
    update_config_value(config, "xunfei_app_id", "app-id")
    update_config_value(config, "xunfei_api_key", "api-key")
    update_config_value(config, "xunfei_api_secret", "api-secret")
    update_config_value(config, "voice_input_shortcut", "Ctrl+Alt+V")

    assert config.asr.provider == "local"
    assert config.asr.use_gpu is True
    assert config.asr.language is None
    assert config.ai_model_api_key == "local-only-secret"
    assert config.has_xunfei_credentials is True
    assert config.voice_input_shortcut == "Ctrl+Alt+V"

    update_config_value(config, "asr.provider", "xunfei")
    assert config.asr.provider == "xunfei"
    with pytest.raises(ValueError, match="布尔值"):
        update_config_value(config, "asr.use_gpu", "maybe")
    with pytest.raises(ValueError, match="未知配置项"):
        update_config_value(config, "asr.unknown", "value")
