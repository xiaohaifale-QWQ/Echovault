from core.config import AppConfig, config_manager
from tests.qt_test_app import ensure_app, keep_widget
from ui.settings_dialog import SettingsDialog


def test_audio_source_changes_are_saved_without_accepting_dialog(monkeypatch):
    ensure_app()
    saved = []
    config = AppConfig()
    monkeypatch.setattr(config_manager, "config", config)
    monkeypatch.setattr(config_manager, "save", lambda: saved.append(True))
    dialog = keep_widget(SettingsDialog(config, section="audio_sources"))
    dialog.audio_source_manager._sources = [
        {
            "type": "lx_js",
            "id": "lx-demo-kw",
            "name": "Demo · 酷我",
            "script_path": "C:/sources/demo.js",
            "script_sha256": "abc",
            "source_key": "kw",
            "platform_name": "酷我",
            "qualities": ["128k"],
            "metadata": {"name": "Demo"},
            "authorized": True,
            "enabled": True,
        }
    ]

    dialog.audio_source_manager.sources_changed.emit()

    assert saved == [True]
    assert config.audio_sources[0]["id"] == "lx-demo-kw"
    dialog.reject()
