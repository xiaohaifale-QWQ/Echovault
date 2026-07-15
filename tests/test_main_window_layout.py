from PyQt6.QtWidgets import QMessageBox

from core.config import AppConfig
from core.online_lyrics import LyricsMatch
from tests.qt_test_app import ensure_app, keep_widget
from ui.main_window import MainWindow
from ui.online_lyrics_panel import OnlineLyricsAction


def test_main_window_has_five_right_tabs_and_no_scattered_batch_buttons(monkeypatch):
    ensure_app()
    monkeypatch.setattr("ui.main_window.config_manager.load", AppConfig)
    monkeypatch.setattr(
        "ui.main_window.build_environment_report",
        lambda _config: {"ffmpeg": {"available": True}},
    )

    window = keep_widget(MainWindow())

    assert [
        window.right_tabs.tabText(index)
        for index in range(window.right_tabs.count())
    ] == ["详情", "素材库", "在线匹配", "批量处理", "同步"]
    assert not hasattr(window.song_list_panel, "btn_batch")
    assert not hasattr(window.detail_panel, "btn_batch_translate")


def test_main_window_applies_cross_merge_with_backup(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr("ui.main_window.config_manager.load", AppConfig)
    monkeypatch.setattr(
        "ui.main_window.build_environment_report",
        lambda _config: {"ffmpeg": {"available": True}},
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    window = keep_widget(MainWindow())
    media_path = tmp_path / "song.mp3"
    lrc_path = media_path.with_suffix(".lrc")
    local = "[00:01.230]local one\n[00:04.50]local two\n"
    online = "[00:10.00]online one\n[00:30.000]online two\n"
    lrc_path.write_text(local, encoding="utf-8")
    window.online_lyrics_panel._song = {
        "name": media_path.name,
        "path": str(media_path),
        "lrc_path": str(lrc_path),
        "has_lrc": True,
    }
    match = LyricsMatch(1, "song", "", "", 30, False, "", online, 95)
    payload = OnlineLyricsAction(match, local, online)

    window._on_online_lyrics_action(
        str(media_path), payload, "merge_local_timeline"
    )

    assert lrc_path.read_text(encoding="utf-8") == (
        "[00:01.230]online one\n[00:04.50]online two\n"
    )
    assert lrc_path.with_suffix(".lrc.bak").read_text(encoding="utf-8") == local
