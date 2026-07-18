from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox

from core.config import AppConfig
from core.online_lyrics import LyricsMatch
from tests.qt_test_app import ensure_app, keep_widget
from ui.main_window import MainWindow
from ui.online_lyrics_panel import CoverApplyAction, OnlineLyricsAction, TagApplyAction
from ui.theme import polish_widget_tree


def test_main_window_uses_four_task_workspaces_and_right_ai_drawer(monkeypatch):
    ensure_app()
    monkeypatch.setattr("ui.main_window.config_manager.load", AppConfig)
    monkeypatch.setattr(
        "ui.main_window.build_environment_report",
        lambda _config: {"ffmpeg": {"available": True}},
    )

    window = keep_widget(MainWindow())

    assert [button.text() for button in window.navigation_buttons.values()] == [
        "素材",
        "歌词与标签",
        "音频编辑",
        "导出与传输",
    ]
    assert window.workspace_stack.currentWidget() is window.workspace_pages["materials"]
    assert [window.lyrics_tabs.tabText(index) for index in range(3)] == [
        "在线歌词与封面",
        "本地识别编辑",
        "歌词核对",
    ]
    assert [window.audio_tabs.tabText(index) for index in range(2)] == [
        "音频编辑",
        "人声分离",
    ]
    assert [window.transfer_tabs.tabText(index) for index in range(2)] == [
        "手机接收与回传",
        "批量任务",
    ]
    assert window.outer_splitter.widget(1) is window.ai_chat_panel
    assert window.ai_chat_panel.isHidden()
    assert window.menuBar().isHidden()
    assert window.global_search.placeholderText() == "搜索素材、歌词、标签或功能"
    assert window.top_settings_button.text() == "设置"
    assert not hasattr(window, "batch_shortcut_button")
    assert all(not button.isEnabled() for button in window.material_action_buttons)
    assert window.model_library_action.text() == "模型库"
    assert window.model_library_action in window.menuBar().actions()
    assert not hasattr(window.song_list_panel, "btn_batch")
    assert not hasattr(window.detail_panel, "btn_batch_translate")

    window._switch_workspace("lyrics")
    window.lyrics_tabs.setCurrentIndex(2)
    assert window.workspace_stack.currentWidget() is window.workspace_pages["lyrics"]
    assert "本地识别歌词" in window.online_comparison_panel.local_editor.parent().title()
    assert "在线匹配歌词" in window.online_comparison_panel.online_editor.parent().title()

    window._switch_workspace("audio")
    window.audio_tabs.setCurrentIndex(1)
    assert window.workspace_stack.currentWidget() is window.workspace_pages["audio"]
    assert window.vocal_lyrics_panel.title_label.text() == "实时歌词"

    window.global_search.setText("音频降噪")
    window._submit_global_search()
    assert window.workspace_stack.currentWidget() is window.workspace_pages["audio"]
    window.global_search.setText("批量")
    window._submit_global_search()
    assert window.workspace_stack.currentWidget() is window.workspace_pages["transfer"]
    assert window.transfer_tabs.currentWidget() is window.batch_operations_panel
    window.global_search.setText("歌词核对")
    window._submit_global_search()
    assert window.lyrics_tabs.currentIndex() == 2
    window.global_search.setText("本地识别")
    window._submit_global_search()
    assert window.lyrics_tabs.currentIndex() == 1
    window.global_search.setText("在线封面")
    window._submit_global_search()
    assert window.lyrics_tabs.currentIndex() == 0

    polish_widget_tree(window)
    assert window.statusbar.minimumHeight() >= 30
    assert window.btn_stop_transcribe.objectName() == "statusStopButton"
    assert window.btn_stop_transcribe.minimumHeight() == 24
    assert window.btn_stop_transcribe.maximumHeight() == 24
    assert window.btn_stop_transcribe.property("buttonRole") == "danger"
    assert window.detail_panel.btn_transcribe.property("buttonRole") == "primary"
    assert (
        window.audio_editor_panel.tool_pages["trim"].run_button.property("buttonRole") == "primary"
    )
    assert window.sync_panel.send_button.property("buttonRole") == "primary"
    window._on_song_selected({"path": "C:/music/song.mp3", "has_lrc": False})
    assert all(button.isEnabled() for button in window.material_action_buttons)

    monkeypatch.setattr(
        "core.ai_assistant.settings_from_config",
        lambda _config: SimpleNamespace(
            requires_api_key=False,
            api_key="",
            base_url="http://127.0.0.1:11434/v1",
            model="local-model",
        ),
    )
    window._toggle_ai_mode()
    assert not window.ai_chat_panel.isHidden()
    assert window.outer_splitter.sizes()[1] > 0
    window._toggle_ai_mode()
    assert window.ai_chat_panel.isHidden()


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

    window._on_online_lyrics_action(str(media_path), payload, "merge_local_timeline")

    assert lrc_path.read_text(encoding="utf-8") == ("[00:01.230]online one\n[00:04.50]online two\n")
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


def test_main_window_writes_selected_cover_and_refreshes_thumbnail(monkeypatch, tmp_path):
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


def test_main_window_writes_audio_tags_from_online_workspace(monkeypatch, tmp_path):
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
        "ui.main_window.write_tags",
        lambda *args: written.append(args),
    )
    window = keep_widget(MainWindow())
    monkeypatch.setattr(window.online_lyrics_panel, "reload_tags", lambda: None)
    media_path = str(tmp_path / "song.flac")
    values = {
        "title": "Song",
        "artist": "Singer",
        "album": "Album",
        "year": "2026",
        "track": "3",
    }

    window._on_online_lyrics_action(
        media_path,
        TagApplyAction(values),
        "apply_tags",
    )

    assert written == [(media_path, values)]
