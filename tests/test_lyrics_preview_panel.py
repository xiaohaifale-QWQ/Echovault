from tests.qt_test_app import ensure_app, keep_widget
from ui.lyrics_preview_panel import LyricsPreviewPanel


def test_preview_shows_not_recognized_for_material_without_lrc(tmp_path):
    ensure_app()
    panel = keep_widget(LyricsPreviewPanel())
    panel.show_song(
        {
            "name": "clip.mp4",
            "lrc_path": str(tmp_path / "clip.lrc"),
            "has_lrc": False,
        }
    )

    assert panel.text.toPlainText() == "暂未识别"


def test_double_click_edit_mode_saves_lrc_in_place(tmp_path):
    ensure_app()
    lrc_path = tmp_path / "clip.lrc"
    lrc_path.write_text("[00:01.00]原歌词", encoding="utf-8")
    panel = keep_widget(LyricsPreviewPanel())
    panel.show_song({"name": "clip.mp4", "lrc_path": str(lrc_path), "has_lrc": True})

    panel._start_editing()
    panel.text.setPlainText("[00:01.00]修改后的歌词")
    panel._save()

    assert lrc_path.read_text(encoding="utf-8") == "[00:01.00]修改后的歌词"
    assert panel.text.isReadOnly()
    assert not panel.save_button.isEnabled()


def test_preview_supports_online_comparison_title_and_playback_highlight(tmp_path):
    ensure_app()
    lrc_path = tmp_path / "song.lrc"
    lrc_path.write_text(
        "[00:01.00]first\n[00:13.00]second\n", encoding="utf-8"
    )
    panel = keep_widget(LyricsPreviewPanel())
    panel.show_song({"name": "song.mp3", "lrc_path": str(lrc_path), "has_lrc": True})
    panel.set_online_comparison_mode(True)

    assert panel.title_label.text() == "本软件识别歌词（左侧）"
    assert panel.text.highlight_at(13.0) == 1
    assert len(panel.text.extraSelections()) == 1
