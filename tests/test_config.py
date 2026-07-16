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
    manager.config.ai_provider = "local"
    manager.config.local_ai_base_url = "http://127.0.0.1:1234/v1"
    manager.config.local_ai_model_name = "local-model"
    manager.config.local_ai_api_key = "local-ai-secret"
    manager.config.translation_engine = "local"
    manager.config.translation_source_language = "ja"
    manager.config.translation_target_language = "zh"
    manager.config.voice_input_shortcut = "Ctrl+Alt+V"
    manager.config.music_dirs = ["D:/Music"]
    manager.config.video_dirs = ["D:/Video"]
    manager.config.music_select_all = True
    manager.config.video_select_all = True
    manager.config.video_time_offsets = {"D:/Video": 120}
    manager.config.asr.vocal_separation_model = "htdemucs_ft"
    manager.config.asr.vocal_separation_use_gpu = True
    manager.config.transfer.receive_dir = "D:/PhoneInbox"
    manager.config.transfer.auto_start_receiver = True
    manager.config.transfer.device_alias = "Echovault-Test"
    manager.config.transfer.concurrent_uploads = 3
    manager.config.transfer.strict_hash = False
    manager.config.transfer.keep_session_days = 14

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
    assert loaded.ai_provider == "local"
    assert loaded.local_ai_base_url == "http://127.0.0.1:1234/v1"
    assert loaded.local_ai_model_name == "local-model"
    assert loaded.local_ai_api_key == "local-ai-secret"
    assert loaded.translation_engine == "local"
    assert loaded.translation_source_language == "ja"
    assert loaded.translation_target_language == "zh"
    assert loaded.voice_input_shortcut == "Ctrl+Alt+V"
    assert loaded.music_dirs == ["D:/Music"]
    assert loaded.video_dirs == ["D:/Video"]
    assert loaded.music_select_all is True
    assert loaded.video_select_all is True
    assert loaded.video_time_offsets == {"D:/Video": 120}
    assert loaded.asr.vocal_separation_model == "htdemucs_ft"
    assert loaded.asr.vocal_separation_use_gpu is True
    assert loaded.transfer.receive_dir == "D:/PhoneInbox"
    assert loaded.transfer.auto_start_receiver is True
    assert loaded.transfer.device_alias == "Echovault-Test"
    assert loaded.transfer.concurrent_uploads == 3
    assert loaded.transfer.strict_hash is False
    assert loaded.transfer.keep_session_days == 14

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
            "local_ai_api_key": "file-local-ai-secret",
            "local_ai_base_url": "http://file.invalid/v1",
            "local_ai_model_name": "file-model",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_API_KEY", "environment-secret")
    monkeypatch.setenv("XUNFEI_APP_ID", "environment-app-id")
    monkeypatch.setenv("XUNFEI_API_KEY", "environment-xunfei")
    monkeypatch.setenv("XUNFEI_API_SECRET", "environment-api-secret")
    monkeypatch.setenv("ECHOVAULT_LOCAL_AI_API_KEY", "environment-local-ai-secret")
    monkeypatch.setenv("ECHOVAULT_LOCAL_AI_BASE_URL", "http://environment.invalid/v1")
    monkeypatch.setenv("ECHOVAULT_LOCAL_AI_MODEL", "environment-model")

    loaded = ConfigManager(path).load()

    assert loaded.groq_api_key == "environment-secret"
    assert loaded.xunfei_app_id == "environment-app-id"
    assert loaded.xunfei_api_key == "environment-xunfei"
    assert loaded.xunfei_api_secret == "environment-api-secret"
    assert loaded.local_ai_api_key == "environment-local-ai-secret"
    assert loaded.local_ai_base_url == "http://environment.invalid/v1"
    assert loaded.local_ai_model_name == "environment-model"


def test_update_config_value_validates_provider_and_booleans():
    config = AppConfig()

    update_config_value(config, "asr.provider", "local")
    update_config_value(config, "asr.use_gpu", "yes")
    update_config_value(config, "asr.vocal_separation_model", "mdx_extra_q")
    update_config_value(config, "asr.vocal_separation_use_gpu", "yes")
    update_config_value(config, "asr.language", "auto")
    update_config_value(config, "ai_model_api_key", "local-only-secret")
    update_config_value(config, "ai_provider", "local")
    update_config_value(config, "local_ai_base_url", "http://127.0.0.1:1234/v1/")
    update_config_value(config, "local_ai_model_name", "qwen")
    update_config_value(config, "local_ai_api_key", "optional-key")
    update_config_value(config, "translation_engine", "local")
    update_config_value(config, "translation_source_language", "en")
    update_config_value(config, "translation_target_language", "zh")
    update_config_value(config, "xunfei_app_id", "app-id")
    update_config_value(config, "xunfei_api_key", "api-key")
    update_config_value(config, "xunfei_api_secret", "api-secret")
    update_config_value(config, "voice_input_shortcut", "Ctrl+Alt+V")

    assert config.asr.provider == "local"
    assert config.asr.use_gpu is True
    assert config.asr.vocal_separation_model == "mdx_extra_q"
    assert config.asr.vocal_separation_use_gpu is True
    assert config.asr.language is None
    assert config.ai_model_api_key == "local-only-secret"
    assert config.ai_provider == "local"
    assert config.local_ai_base_url == "http://127.0.0.1:1234/v1"
    assert config.local_ai_model_name == "qwen"
    assert config.local_ai_api_key == "optional-key"
    assert config.translation_engine == "local"
    assert config.translation_source_language == "en"
    assert config.translation_target_language == "zh"
    assert config.has_xunfei_credentials is True
    assert config.voice_input_shortcut == "Ctrl+Alt+V"

    update_config_value(config, "translation_source_language", "auto")
    assert config.translation_source_language == "auto"

    update_config_value(config, "asr.provider", "xunfei")
    assert config.asr.provider == "xunfei"
    with pytest.raises(ValueError, match="布尔值"):
        update_config_value(config, "asr.use_gpu", "maybe")
    with pytest.raises(ValueError, match="未知配置项"):
        update_config_value(config, "asr.unknown", "value")
    with pytest.raises(ValueError, match="AI Provider"):
        update_config_value(config, "ai_provider", "unsupported")
