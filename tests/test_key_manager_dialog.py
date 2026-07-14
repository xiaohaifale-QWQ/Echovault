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
    dialog.xunfei_input.setText("xunfei-key")
    dialog.ai_input.setText("ai-key")

    dialog._save()

    assert config.groq_api_key == "groq-key"
    assert config.xunfei_api_key == "xunfei-key"
    assert config.ai_model_api_key == "ai-key"
    assert (tmp_path / "config.json").is_file()
