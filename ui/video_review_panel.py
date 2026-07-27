"""Video playback with synchronized, adjustable subtitle review."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
)

from core.online_lyrics import timed_text_entries
from core.video_library import video_processing_outputs
from ui.playback_coordinator import PlaybackSession

_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:\.(\d{2,3}))?\]")


def shift_lrc_timestamps(content: str, offset_seconds: float) -> str:
    """Shift every synchronized LRC timestamp while preserving all other text."""

    def replace(match: re.Match) -> str:
        fraction = match.group(3) or "00"
        milliseconds = int(fraction.ljust(3, "0")[:3])
        seconds = int(match.group(1)) * 60 + int(match.group(2)) + milliseconds / 1000
        shifted = max(0.0, seconds + offset_seconds)
        minutes, remainder = divmod(shifted, 60)
        return f"[{int(minutes):02d}:{remainder:05.2f}]"

    return _TIMESTAMP.sub(replace, content)


class VideoReviewPanel(QGroupBox):
    """Persistent video processing outputs and synchronized subtitle calibration."""

    subtitle_saved = pyqtSignal(str)
    playback_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("处理结果与播放字幕", parent)
        self._video_path = ""
        self._audio_path = ""
        self._subtitle_path = ""
        self._raw_content = ""
        self._entries = []
        self._active_index = -1
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._playback_session = PlaybackSession(self._player)
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        results = QFrame()
        results.setObjectName("videoResultStrip")
        result_layout = QGridLayout(results)
        result_layout.setContentsMargins(10, 7, 10, 7)
        result_layout.addWidget(QLabel("提取音频"), 0, 0)
        self.audio_result = QLabel("尚未生成")
        self.audio_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        result_layout.addWidget(self.audio_result, 0, 1)
        self.open_audio_button = QPushButton("打开")
        self.open_audio_button.clicked.connect(lambda: self._open_output(self._audio_path))
        result_layout.addWidget(self.open_audio_button, 0, 2)
        result_layout.addWidget(QLabel("识别文字"), 1, 0)
        self.subtitle_result = QLabel("尚未生成")
        self.subtitle_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        result_layout.addWidget(self.subtitle_result, 1, 1)
        self.open_subtitle_button = QPushButton("打开")
        self.open_subtitle_button.clicked.connect(
            lambda: self._open_output(self._subtitle_path)
        )
        result_layout.addWidget(self.open_subtitle_button, 1, 2)
        result_layout.setColumnStretch(1, 1)
        outer.addWidget(results)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        player_panel = QFrame()
        player_panel.setObjectName("videoPlayerPanel")
        player_layout = QVBoxLayout(player_panel)
        player_layout.setContentsMargins(0, 0, 0, 0)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(210)
        self.video_widget.setStyleSheet("background:#111827;border-radius:8px")
        self._player.setVideoOutput(self.video_widget)
        player_layout.addWidget(self.video_widget, 1)
        transport = QHBoxLayout()
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self._toggle_playback)
        transport.addWidget(self.play_button)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self._player.setPosition)
        transport.addWidget(self.position_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        transport.addWidget(self.time_label)
        player_layout.addLayout(transport)
        splitter.addWidget(player_panel)

        subtitle_panel = QFrame()
        subtitle_panel.setObjectName("subtitleCalibrationPanel")
        subtitle_layout = QVBoxLayout(subtitle_panel)
        subtitle_layout.setContentsMargins(8, 0, 0, 0)
        title_row = QHBoxLayout()
        title = QLabel("同步字幕")
        title.setStyleSheet("font-weight:700;font-size:14px")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(QLabel("整体偏移"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-600.0, 600.0)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setSuffix(" 秒")
        self.offset_spin.valueChanged.connect(self._refresh_subtitles)
        title_row.addWidget(self.offset_spin)
        subtitle_layout.addLayout(title_row)
        self.subtitle_list = QListWidget()
        self.subtitle_list.setAlternatingRowColors(True)
        self.subtitle_list.itemDoubleClicked.connect(self._seek_to_item)
        subtitle_layout.addWidget(self.subtitle_list, 1)
        calibrate_row = QHBoxLayout()
        for label, delta in (("提前 0.1 秒", -0.1), ("延后 0.1 秒", 0.1)):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=delta: self.offset_spin.setValue(
                    self.offset_spin.value() + value
                )
            )
            calibrate_row.addWidget(button)
        calibrate_row.addStretch()
        self.save_button = QPushButton("保存字幕校准")
        self.save_button.setObjectName("primaryAction")
        self.save_button.clicked.connect(self._save_calibration)
        calibrate_row.addWidget(self.save_button)
        subtitle_layout.addLayout(calibrate_row)
        splitter.addWidget(subtitle_panel)
        splitter.setSizes([620, 500])
        outer.addWidget(splitter, 1)

        self._player.positionChanged.connect(self._position_changed)
        self._player.durationChanged.connect(self._duration_changed)
        self._player.playbackStateChanged.connect(
            lambda state: self.play_button.setText(
                "暂停"
                if state == QMediaPlayer.PlaybackState.PlayingState
                else "播放"
            )
        )
        self.setStyleSheet(
            """
            QFrame#videoResultStrip {
                background:#F4F8FC;border:1px solid #DCE6F0;border-radius:8px;
            }
            QFrame#subtitleCalibrationPanel {
                background:#FFFFFF;border-left:1px solid #E3E9F0;
            }
            """
        )
        self._refresh_state()

    def set_video(self, song: dict):
        self._video_path = str(song.get("path", ""))
        expected_audio, expected_subtitle = video_processing_outputs(self._video_path)
        self.set_results(
            self._video_path,
            str(song.get("output_audio_path") or expected_audio),
            str(song.get("output_text_path") or song.get("lrc_path") or expected_subtitle),
        )

    def set_results(self, video_path: str, audio_path: str, subtitle_path: str):
        self._video_path = video_path
        self._audio_path = audio_path if Path(audio_path).is_file() else ""
        self._subtitle_path = subtitle_path if Path(subtitle_path).is_file() else ""
        self._player.stop()
        if Path(video_path).is_file():
            self._player.setSource(QUrl.fromLocalFile(str(Path(video_path).resolve())))
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(0.0)
        self.offset_spin.blockSignals(False)
        self._raw_content = ""
        if self._subtitle_path:
            try:
                self._raw_content = Path(self._subtitle_path).read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                self._raw_content = ""
        self._refresh_subtitles()
        self._refresh_state()

    def _refresh_state(self):
        self.audio_result.setText(
            self._audio_path if self._audio_path else "处理后将在这里显示完整音频文件"
        )
        self.subtitle_result.setText(
            self._subtitle_path if self._subtitle_path else "处理后将在这里显示字幕文字文件"
        )
        self.open_audio_button.setEnabled(bool(self._audio_path))
        self.open_subtitle_button.setEnabled(bool(self._subtitle_path))
        self.play_button.setEnabled(bool(self._video_path and Path(self._video_path).is_file()))
        self.save_button.setEnabled(bool(self._subtitle_path and self._raw_content))

    def _refresh_subtitles(self, *_args):
        content = shift_lrc_timestamps(self._raw_content, self.offset_spin.value())
        self._entries = timed_text_entries(content)
        self.subtitle_list.clear()
        for entry in self._entries:
            minutes, seconds = divmod(entry.timestamp, 60)
            item = QListWidgetItem(f"{int(minutes):02d}:{seconds:05.2f}   {entry.text}")
            item.setData(Qt.ItemDataRole.UserRole, entry.timestamp)
            self.subtitle_list.addItem(item)
        self._active_index = -1

    def _toggle_playback(self):
        if not self._video_path:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self.playback_started.emit()
            self._playback_session.play(self._player)

    def _position_changed(self, position_ms: int):
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(position_ms)
        self.position_slider.blockSignals(False)
        self.time_label.setText(
            f"{self._format_ms(position_ms)} / {self._format_ms(self._player.duration())}"
        )
        seconds = position_ms / 1000.0
        active = -1
        for index, entry in enumerate(self._entries):
            if entry.timestamp <= seconds:
                active = index
            else:
                break
        if active != self._active_index and active >= 0:
            self._active_index = active
            self.subtitle_list.setCurrentRow(active)
            self.subtitle_list.scrollToItem(
                self.subtitle_list.item(active),
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )

    def _duration_changed(self, duration_ms: int):
        self.position_slider.setRange(0, max(0, duration_ms))
        self.time_label.setText(
            f"{self._format_ms(self._player.position())} / {self._format_ms(duration_ms)}"
        )

    def _seek_to_item(self, item: QListWidgetItem):
        self._player.setPosition(int(float(item.data(Qt.ItemDataRole.UserRole)) * 1000))

    def _save_calibration(self):
        if not self._subtitle_path:
            return
        path = Path(self._subtitle_path)
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, backup)
            content = shift_lrc_timestamps(self._raw_content, self.offset_spin.value())
            path.write_text(content, encoding="utf-8", newline="\n")
        except OSError:
            return
        self._raw_content = content
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(0.0)
        self.offset_spin.blockSignals(False)
        self._refresh_subtitles()
        self.subtitle_saved.emit(str(path))

    @staticmethod
    def _open_output(path: str):
        if path and Path(path).is_file():
            os.startfile(str(Path(path).parent))

    @staticmethod
    def _format_ms(milliseconds: int) -> str:
        total_seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
