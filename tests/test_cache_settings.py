from core.config import AppConfig
from tests.qt_test_app import ensure_app, keep_widget
from ui.settings_dialog import SettingsDialog


def test_cache_settings_show_file_counts_and_sizes(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr("ui.settings_dialog.voice_cache_dir", lambda: tmp_path / "voice")
    monkeypatch.setattr(
        "ui.settings_dialog.sent_transfer_cache_dir", lambda: tmp_path / "sent"
    )
    monkeypatch.setattr(
        "ui.settings_dialog.cache_stats",
        lambda: {
            "voice_count": 2,
            "voice_size": 1024,
            "sent_count": 3,
            "sent_size": 2 * 1024 * 1024,
            "total_count": 5,
            "total_size": 2 * 1024 * 1024 + 1024,
        },
    )

    dialog = keep_widget(SettingsDialog(AppConfig(), section="cache"))

    assert "2 个文件" in dialog.voice_cache_stats.text()
    assert "1.00 KB" in dialog.voice_cache_stats.text()
    assert "3 个文件" in dialog.sent_cache_stats.text()
    assert "2.00 MB" in dialog.sent_cache_stats.text()
    assert "5 个文件" in dialog.cache_status.text()
