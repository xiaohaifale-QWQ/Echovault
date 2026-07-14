from PyQt6.QtWidgets import QApplication, QLabel

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
    dialog.xunfei_app_id_input.setText("xunfei-app-id")
    dialog.xunfei_api_key_input.setText("xunfei-key")
    dialog.xunfei_api_secret_input.setText("xunfei-api-secret")
    dialog.ai_input.setText("ai-key")
    dialog.ai_base_url.setText("https://example.invalid/")
    dialog.ai_model_name.setText("test-model")

    dialog._save()

    assert config.groq_api_key == "groq-key"
    assert config.groq_proxy_url == "http://127.0.0.1:7890"
    assert config.xunfei_app_id == "xunfei-app-id"
    assert config.xunfei_api_key == "xunfei-key"
    assert config.xunfei_api_secret == "xunfei-api-secret"
    assert config.has_xunfei_credentials is True
    assert config.ai_model_api_key == "ai-key"
    assert config.ai_base_url == "https://example.invalid"
    assert config.ai_model_name == "test-model"
    assert (tmp_path / "config.json").is_file()


def test_provider_names_link_to_their_official_consoles():
    _app()
    dialog = KeyManagerDialog(AppConfig())
    links = {label.text() for label in dialog.findChildren(QLabel) if "href=" in label.text()}

    assert any("https://console.groq.com/keys" in link for link in links)
    assert any("https://console.xfyun.cn/" in link for link in links)
    assert any("https://platform.deepseek.com/api_keys" in link for link in links)
