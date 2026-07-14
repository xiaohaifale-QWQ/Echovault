from PyQt6.QtWidgets import QApplication

from ui.lyrics_preview_panel import LyricsPreviewPanel


def _app():
    return QApplication.instance() or QApplication([])


def test_preview_shows_not_recognized_for_material_without_lrc(tmp_path):
    _app()
    panel = LyricsPreviewPanel()
    panel.show_song(
        {
            "name": "clip.mp4",
            "lrc_path": str(tmp_path / "clip.lrc"),
            "has_lrc": False,
        }
    )

    assert panel.text.toPlainText() == "暂未识别"


def test_double_click_edit_mode_saves_lrc_in_place(tmp_path):
    _app()
    lrc_path = tmp_path / "clip.lrc"
    lrc_path.write_text("[00:01.00]原歌词", encoding="utf-8")
    panel = LyricsPreviewPanel()
    panel.show_song({"name": "clip.mp4", "lrc_path": str(lrc_path), "has_lrc": True})

    panel._start_editing()
    panel.text.setPlainText("[00:01.00]修改后的歌词")
    panel._save()

    assert lrc_path.read_text(encoding="utf-8") == "[00:01.00]修改后的歌词"
    assert panel.text.isReadOnly()
    assert not panel.save_button.isEnabled()
