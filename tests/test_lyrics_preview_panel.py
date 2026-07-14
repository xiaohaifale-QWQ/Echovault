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
