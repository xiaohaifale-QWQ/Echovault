from PyQt6.QtWidgets import QApplication

from core.config import AppConfig, config_manager
from ui.key_manager_dialog import KeyManagerDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_key_manager_saves_all_keys_locally(tmp_path, monkeypatch):
    _app()
    monkeypatch.setattr(config_manager, "config_path", tmp_path / "config.json")
    config = AppConfig()
    dialog = KeyManagerDialog(config)
    dialog.groq_input.setText("groq-key")
    dialog.groq_proxy_input.setText("http://127.0.0.1:7890")
    dialog.xunfei_input.setText("xunfei-key")
    dialog.ai_input.setText("ai-key")
    dialog.ai_base_url.setText("https://example.invalid/")
    dialog.ai_model_name.setText("test-model")

    dialog._save()

    assert config.groq_api_key == "groq-key"
    assert config.groq_proxy_url == "http://127.0.0.1:7890"
    assert config.xunfei_api_key == "xunfei-key"
    assert config.ai_model_api_key == "ai-key"
    assert config.ai_base_url == "https://example.invalid"
    assert config.ai_model_name == "test-model"
    assert (tmp_path / "config.json").is_file()
