"""Lyrics preview with inline editing for material-library items."""

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LyricsTextEdit(QTextEdit):
    """Request inline editing when a read-only preview is double-clicked."""

    edit_requested = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.edit_requested.emit()
        super().mouseDoubleClickEvent(event)


class LyricsPreviewPanel(QWidget):
    lyrics_saved = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        header = QHBoxLayout()
        title = QLabel("歌词预览")
        title.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        header.addWidget(title)
        header.addStretch()
        self.save_button = QPushButton("保存")
        self.save_button.setToolTip("双击歌词区域后，保存对 LRC 文件的修改")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        header.addWidget(self.save_button)
        layout.addLayout(header)
        self.song_label = QLabel("切换至素材库时显示当前素材的歌词")
        self.song_label.setStyleSheet("color:#666;padding:2px 4px")
        self.song_label.setWordWrap(True)
        layout.addWidget(self.song_label)
        self.text = LyricsTextEdit()
        self.text.setReadOnly(True)
        self.text.edit_requested.connect(self._start_editing)
        self.text.setPlaceholderText("选择并识别音频或视频素材后，歌词会显示在这里…")
        self.text.setStyleSheet(
            "QTextEdit{font-family:Consolas,Microsoft YaHei;font-size:13px;"
            "background:#fafafa;border:1px solid #e0e0e0;border-radius:4px}"
        )
        layout.addWidget(self.text)
        self._lrc_path: Path | None = None

    def show_song(self, song: dict):
        if not song:
            self.clear()
            return
        self._lrc_path = None
        self.save_button.setEnabled(False)
        self.text.setReadOnly(True)
        self.song_label.setText(Path(song.get("name", "")).stem)
        lrc_path = song.get("lrc_path")
        if not song.get("has_lrc") or not lrc_path:
            self.text.setPlainText("暂未识别")
            return
        try:
            self._lrc_path = Path(lrc_path)
            self.text.setPlainText(self._lrc_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            self._lrc_path = None
            self.text.setPlainText(f"无法读取歌词：{exc}")

    def _start_editing(self):
        if not self._lrc_path:
            return
        self.text.setReadOnly(False)
        self.text.setFocus()
        self.save_button.setEnabled(True)
        self.song_label.setText(f"{self._lrc_path.stem}（编辑中）")

    def _save(self):
        if not self._lrc_path or self.text.isReadOnly():
            return
        temp_path = self._lrc_path.with_suffix(self._lrc_path.suffix + ".tmp")
        try:
            temp_path.write_text(self.text.toPlainText(), encoding="utf-8", newline="\n")
            temp_path.replace(self._lrc_path)
        except OSError as exc:
            self.song_label.setText(f"保存失败：{exc}")
            return
        self.text.setReadOnly(True)
        self.save_button.setEnabled(False)
        self.song_label.setText(f"{self._lrc_path.stem}（已保存）")
        self.lyrics_saved.emit(str(self._lrc_path))

    def clear(self):
        self._lrc_path = None
        self.text.setReadOnly(True)
        self.save_button.setEnabled(False)
        self.song_label.setText("切换至素材库时显示当前素材的歌词")
        self.text.clear()
