"""Compact synchronized lyrics card for the main navigation rail."""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from core.online_lyrics import TimedTextEntry, timed_text_entries


class NavigationLyricsCard(QFrame):
    """Show the current song and keep its active LRC line centered."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navigationLyricsCard")
        self.setFixedHeight(224)
        self._media_path = ""
        self._lrc_path: Path | None = None
        self._entries: list[TimedTextEntry] = []
        self._timestamps: list[float] = []
        self._current_index = -2

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(4)
        caption = QLabel("正在播放")
        caption.setObjectName("navigationLyricsCaption")
        header.addWidget(caption)
        header.addStretch()
        self.time_label = QLabel("00:00")
        self.time_label.setObjectName("navigationLyricsTime")
        header.addWidget(self.time_label)
        layout.addLayout(header)

        self.song_label = QLabel("尚未选择歌曲")
        self.song_label.setObjectName("navigationLyricsSong")
        self.song_label.setWordWrap(True)
        self.song_label.setMaximumHeight(38)
        layout.addWidget(self.song_label)

        self.lyrics_list = QListWidget()
        self.lyrics_list.setObjectName("navigationLyricsList")
        self.lyrics_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lyrics_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lyrics_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.lyrics_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lyrics_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lyrics_list.setWordWrap(True)
        self.lyrics_list.setSpacing(2)
        layout.addWidget(self.lyrics_list, 1)

        self._scroll_animation = QPropertyAnimation(
            self.lyrics_list.verticalScrollBar(), b"value", self
        )
        self._scroll_animation.setDuration(180)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._show_placeholder("选择歌曲后显示同步歌词")

        self.setStyleSheet(
            """
            QFrame#navigationLyricsCard {
                background:#FFFFFF; border:1px solid #DCE4ED; border-radius:11px;
            }
            QLabel#navigationLyricsCaption {
                color:#718096; font-size:9px; font-weight:600;
            }
            QLabel#navigationLyricsTime {
                color:#8A96A7; font-size:9px;
            }
            QLabel#navigationLyricsSong {
                color:#17233A; font-size:12px; font-weight:700;
            }
            QListWidget#navigationLyricsList {
                background:#F7F9FC; border:none; border-radius:8px;
                color:#7B8798; font-size:10px; padding:5px 3px;
                outline:none;
            }
            QListWidget#navigationLyricsList::item {
                border:none; border-radius:6px; padding:5px 4px;
            }
            QListWidget#navigationLyricsList::item:selected {
                background:#E7F1FC; color:#1F6FBB; font-size:11px;
                font-weight:700;
            }
            """
        )

    @property
    def current_lyric_index(self) -> int:
        return self._current_index

    def set_song(self, song: dict) -> None:
        path = Path(str(song.get("path", "")))
        name = str(song.get("name") or path.name)
        self._media_path = str(path)
        self.song_label.setText(Path(name).stem or "未命名素材")
        self.song_label.setToolTip(str(path))
        lrc_value = song.get("lrc_path") or (path.with_suffix(".lrc") if path.name else "")
        self._lrc_path = Path(str(lrc_value)) if lrc_value else None
        self.reload_lyrics()

    def reload_lyrics(self, lrc_path: str | None = None) -> None:
        if lrc_path is not None:
            candidate = Path(lrc_path)
            if self._lrc_path is None or candidate.resolve() != self._lrc_path.resolve():
                return
        self._entries = []
        self._timestamps = []
        self._current_index = -2
        self.time_label.setText("00:00")
        if self._lrc_path is None or not self._lrc_path.is_file():
            self._show_placeholder("暂无同步歌词")
            return
        try:
            content = self._lrc_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            self._show_placeholder("歌词读取失败")
            return
        self._entries = sorted(timed_text_entries(content), key=lambda entry: entry.timestamp)
        self._timestamps = [entry.timestamp for entry in self._entries]
        if not self._entries:
            self._show_placeholder("歌词没有时间轴")
            return
        self.lyrics_list.clear()
        for entry in self._entries:
            item = QListWidgetItem(entry.text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setSizeHint(QSize(0, 34))
            self.lyrics_list.addItem(item)
        self.set_position_ms(0)

    def set_position_ms(self, position: int) -> None:
        position = max(0, int(position))
        seconds = position / 1000.0
        minutes, remainder = divmod(position // 1000, 60)
        self.time_label.setText(f"{minutes:02d}:{remainder:02d}")
        if not self._entries:
            return
        index = bisect_right(self._timestamps, seconds) - 1
        if index == self._current_index:
            return
        self._current_index = index
        if index < 0:
            self.lyrics_list.clearSelection()
            self.lyrics_list.verticalScrollBar().setValue(0)
            return
        start = self.lyrics_list.verticalScrollBar().value()
        self.lyrics_list.setCurrentRow(index)
        self.lyrics_list.scrollToItem(
            self.lyrics_list.item(index),
            QAbstractItemView.ScrollHint.PositionAtCenter,
        )
        target = self.lyrics_list.verticalScrollBar().value()
        if start == target:
            return
        self._scroll_animation.stop()
        self.lyrics_list.verticalScrollBar().setValue(start)
        self._scroll_animation.setStartValue(start)
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    def _show_placeholder(self, text: str) -> None:
        self.lyrics_list.clear()
        item = QListWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(QSize(0, 58))
        self.lyrics_list.addItem(item)
