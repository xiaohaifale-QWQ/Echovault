"""Read-only lyrics preview used beside the material-library view."""

from pathlib import Path

from PyQt6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from core.lrc_parser import parse_lrc_file


class LyricsPreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("歌词预览")
        title.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        layout.addWidget(title)
        self.song_label = QLabel("切换至素材库时显示当前素材的歌词")
        self.song_label.setStyleSheet("color:#666;padding:2px 4px")
        self.song_label.setWordWrap(True)
        layout.addWidget(self.song_label)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("选择并识别音频或视频素材后，歌词会显示在这里…")
        self.text.setStyleSheet(
            "QTextEdit{font-family:Consolas,Microsoft YaHei;font-size:13px;"
            "background:#fafafa;border:1px solid #e0e0e0;border-radius:4px}"
        )
        layout.addWidget(self.text)

    def show_song(self, song: dict):
        if not song:
            self.clear()
            return
        self.song_label.setText(Path(song.get("name", "")).stem)
        lrc_path = song.get("lrc_path")
        if not song.get("has_lrc") or not lrc_path:
            self.text.setPlainText("暂未识别")
            return
        try:
            lrc = parse_lrc_file(lrc_path)
            lines = []
            for line in sorted(lrc.lines, key=lambda item: item.timestamp):
                minutes, seconds = divmod(line.timestamp, 60)
                lines.append(f"[{int(minutes):02d}:{seconds:05.2f}] {line.text}")
            self.text.setPlainText("\n".join(lines))
        except (OSError, UnicodeError, ValueError) as exc:
            self.text.setPlainText(f"无法读取歌词：{exc}")

    def clear(self):
        self.song_label.setText("切换至素材库时显示当前素材的歌词")
        self.text.clear()
