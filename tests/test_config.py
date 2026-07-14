import json

import pytest

from core.config import CONFIG_SCHEMA_VERSION, AppConfig, ConfigManager, update_config_value


def test_config_roundtrip_persists_api_keys(tmp_path):
    path = tmp_path / "config.json"
    manager = ConfigManager(path)
    manager.config.groq_api_key = "groq-secret"
    manager.config.xunfei_api_key = "xunfei-secret"
    manager.config.ai_model_api_key = "ai-secret"
    manager.config.music_dirs = ["D:/Music"]
    manager.config.video_dirs = ["D:/Video"]
    manager.config.music_select_all = True
    manager.config.video_select_all = True
    manager.config.video_time_offsets = {"D:/Video": 120}

    manager.save()
    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "groq-secret"
    assert loaded.xunfei_api_key == "xunfei-secret"
    assert loaded.ai_model_api_key == "ai-secret"
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
        json.dumps({"groq_api_key": "file-secret", "xunfei_api_key": "file-xunfei"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_API_KEY", "environment-secret")
    monkeypatch.setenv("XUNFEI_API_KEY", "environment-xunfei")

    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "environment-secret"
    assert loaded.xunfei_api_key == "environment-xunfei"


def test_update_config_value_validates_provider_and_booleans():
    config = AppConfig()

    update_config_value(config, "asr.provider", "local")
    update_config_value(config, "asr.use_gpu", "yes")
    update_config_value(config, "asr.language", "auto")
    update_config_value(config, "ai_model_api_key", "local-only-secret")

    assert config.asr.provider == "local"
    assert config.asr.use_gpu is True
    assert config.asr.language is None
    assert config.ai_model_api_key == "local-only-secret"

    with pytest.raises(ValueError, match="Provider"):
        update_config_value(config, "asr.provider", "xunfei")
    with pytest.raises(ValueError, match="布尔值"):
        update_config_value(config, "asr.use_gpu", "maybe")
    with pytest.raises(ValueError, match="未知配置项"):
        update_config_value(config, "asr.unknown", "value")
