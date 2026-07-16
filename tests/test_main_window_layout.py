from PyQt6.QtWidgets import QMessageBox

from core.config import AppConfig
from core.online_lyrics import LyricsMatch
from tests.qt_test_app import ensure_app, keep_widget
from ui.main_window import MainWindow
from ui.online_lyrics_panel import CoverApplyAction, OnlineLyricsAction


def test_main_window_has_audio_editor_tab_and_no_scattered_batch_buttons(monkeypatch):
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
    ] == [
        "详情",
        "素材库",
        "在线匹配",
        "人声分离",
        "音频编辑",
        "批量处理",
        "手机传输",
    ]
    assert window.model_library_action.text() == "模型库"
    assert window.model_library_action in window.menuBar().actions()
    assert not hasattr(window.song_list_panel, "btn_batch")
    assert not hasattr(window.detail_panel, "btn_batch_translate")

    window.right_tabs.setCurrentWidget(window.online_lyrics_panel)
    assert window.left_stack.currentWidget() is window.online_comparison_panel
    assert "本地识别歌词" in window.online_comparison_panel.local_editor.parent().title()
    assert "在线匹配歌词" in window.online_comparison_panel.online_editor.parent().title()

    window.right_tabs.setCurrentWidget(window.detail_panel)
    assert window.left_stack.currentWidget() is window.song_list_panel

    window.right_tabs.setCurrentWidget(window.vocal_separation_panel)
    assert window.left_stack.currentWidget() is window.song_list_panel
    assert not window.vocal_lyrics_panel.isHidden()
    assert window.vocal_lyrics_panel.title_label.text() == "实时歌词"
    assert window.content_splitter.count() == 3


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


def test_online_catalog_includes_music_and_video(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr("ui.main_window.config_manager.load", AppConfig)
    monkeypatch.setattr(
        "ui.main_window.build_environment_report",
        lambda _config: {"ffmpeg": {"available": True}},
    )
    music_dir = tmp_path / "music"
    video_dir = tmp_path / "video"
    music_dir.mkdir()
    video_dir.mkdir()
    (music_dir / "Song.mp3").write_bytes(b"audio")
    (video_dir / "Clip.mp4").write_bytes(b"video")
    window = keep_widget(MainWindow())
    window.config.music_dirs = [str(music_dir)]
    window.config.video_dirs = [str(video_dir)]

    window._refresh_online_catalog(force=True)

    assert {song["material_type"] for song in window._online_catalog} == {
        "music",
        "video",
    }
    assert window.online_lyrics_panel.song_selector.count() == 2


def test_main_window_writes_selected_cover_and_refreshes_thumbnail(
    monkeypatch, tmp_path
):
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
    written = []
    monkeypatch.setattr(
        "ui.main_window.write_cover_art",
        lambda *args: written.append(args),
    )
    window = keep_widget(MainWindow())
    refreshed = []
    monkeypatch.setattr(
        window.song_list_panel,
        "invalidate_cover",
        refreshed.append,
    )
    monkeypatch.setattr(window.online_lyrics_panel, "reload_cover", lambda: None)
    media_path = str(tmp_path / "song.mp3")

    window._on_online_lyrics_action(
        media_path,
        CoverApplyAction(b"\xff\xd8\xffcover", "image/jpeg", "本地封面"),
        "apply_cover",
    )

    assert written == [(media_path, b"\xff\xd8\xffcover", "image/jpeg")]
    assert refreshed == [media_path]
