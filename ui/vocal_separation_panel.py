"""Right-side vocal separation workspace with a two-track preview mixer."""

from __future__ import annotations

import shutil
import struct
import tempfile
import wave
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.audio_enhancement import enhancement_model_installed
from core.separation_process import run_separation_process
from core.vocal_separation import (
    SeparationCancelled,
    SeparationResult,
    mix_stems,
    reverse_audio,
    separation_available,
    separation_model_installed,
)
from ui.playback_coordinator import PlaybackSession
from ui.system_audio import apply_system_default_audio


class SeparationWorker(QThread):
    progress = pyqtSignal(int, str)
    completed = pyqtSignal(bool, object)

    def __init__(
        self,
        input_path: str,
        output_dir: str,
        model: str,
        device: str,
        output_content: str,
        denoise: bool,
        dereverb: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.input_path = input_path
        self.output_dir = output_dir
        self.model = model
        self.device = device
        self.output_content = output_content
        self.denoise = denoise
        self.dereverb = dereverb

    def run(self):
        try:
            result = run_separation_process(
                self.input_path,
                self.output_dir,
                model=self.model,
                device=self.device,
                output_content=self.output_content,
                denoise=self.denoise,
                dereverb=self.dereverb,
                progress=lambda percent, message: self.progress.emit(percent, message),
                cancelled=self.isInterruptionRequested,
            )
            self.completed.emit(True, result)
        except SeparationCancelled:
            self.completed.emit(False, "处理已取消")
        except Exception as exc:
            self.completed.emit(False, str(exc))


class MixExportWorker(QThread):
    completed = pyqtSignal(bool, str)

    def __init__(
        self,
        vocals_path: str,
        accompaniment_path: str,
        output_path: str,
        vocal_volume: int,
        accompaniment_volume: int,
        parent=None,
    ):
        super().__init__(parent)
        self.vocals_path = vocals_path
        self.accompaniment_path = accompaniment_path
        self.output_path = output_path
        self.vocal_volume = vocal_volume
        self.accompaniment_volume = accompaniment_volume

    def run(self):
        try:
            result = mix_stems(
                self.vocals_path,
                self.accompaniment_path,
                self.output_path,
                vocal_volume=self.vocal_volume,
                accompaniment_volume=self.accompaniment_volume,
            )
            self.completed.emit(True, str(result))
        except Exception as exc:
            self.completed.emit(False, str(exc))


class ReversePreviewWorker(QThread):
    completed = pyqtSignal(bool, object)

    def __init__(self, paths: dict[str, Path], output_dir: str, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.output_dir = Path(output_dir)

    def run(self):
        try:
            results = {}
            for name, source in self.paths.items():
                if self.isInterruptionRequested():
                    raise SeparationCancelled("倒放准备已取消")
                results[name] = reverse_audio(
                    source, self.output_dir / f"{name}_reverse.wav"
                )
            self.completed.emit(True, results)
        except Exception as exc:
            self.completed.emit(False, str(exc))


class WaveformView(QWidget):
    """Small dependency-free WAV overview with a shared playhead."""

    seek_requested = pyqtSignal(float)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.samples: list[float] = []
        self.playhead = 0.0
        self.setMinimumHeight(76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @staticmethod
    def _decode_sample(data: bytes, width: int) -> int:
        if width == 1:
            return data[0] - 128
        if width == 2:
            return struct.unpack("<h", data)[0]
        if width == 3:
            value = int.from_bytes(data, "little", signed=False)
            return value - (1 << 24) if value & (1 << 23) else value
        if width == 4:
            return struct.unpack("<i", data)[0]
        return 0

    def load_wav(self, file_path: str):
        points = []
        try:
            with wave.open(file_path, "rb") as handle:
                frames = handle.getnframes()
                channels = handle.getnchannels()
                width = handle.getsampwidth()
                maximum = float((1 << (width * 8 - 1)) - 1)
                point_count = min(900, max(1, frames))
                window = min(96, max(1, frames // point_count))
                for index in range(point_count):
                    position = min(frames - 1, int(index * frames / point_count))
                    handle.setpos(position)
                    block = handle.readframes(window)
                    frame_width = channels * width
                    peak = 0
                    for offset in range(0, len(block) - frame_width + 1, frame_width):
                        for channel in range(channels):
                            start = offset + channel * width
                            peak = max(
                                peak,
                                abs(self._decode_sample(block[start : start + width], width)),
                            )
                    points.append(min(1.0, peak / maximum if maximum else 0.0))
        except (OSError, wave.Error, EOFError):
            points = []
        self.samples = points
        self.update()

    def set_playhead(self, ratio: float):
        self.playhead = max(0.0, min(1.0, ratio))
        self.update()

    def _request_seek(self, x: float):
        ratio = max(0.0, min(1.0, x / max(self.width() - 1, 1)))
        self.set_playhead(ratio)
        self.seek_requested.emit(ratio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._request_seek(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._request_seek(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F7FAFC"))
        center = self.height() / 2
        painter.setPen(QPen(QColor("#D8DEE7"), 1))
        painter.drawLine(0, int(center), self.width(), int(center))
        if self.samples:
            path = QPainterPath()
            for index, amplitude in enumerate(self.samples):
                x = index * self.width() / max(len(self.samples) - 1, 1)
                top = center - amplitude * (center - 7)
                bottom = center + amplitude * (center - 7)
                path.moveTo(QPointF(x, top))
                path.lineTo(QPointF(x, bottom))
            painter.setPen(QPen(self.color, 1.2))
            painter.drawPath(path)
        painter.setPen(QPen(QColor("#D64545"), 2))
        x = int(self.playhead * max(self.width() - 1, 0))
        painter.drawLine(x, 0, x, self.height())


class VocalSeparationPanel(QWidget):
    """Separation settings above, synchronized stem mixer below."""

    model_library_requested = pyqtSignal()
    position_changed_ms = pyqtSignal(int)
    playback_started = pyqtSignal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._songs: list[dict] = []
        self._selected_path = ""
        self._result: SeparationResult | None = None
        self._seeking = False
        self._playback_speed = 1
        self._reverse_mode = False
        self._reverse_paths: dict[str, Path] = {}
        self._reverse_temp_dir: str | None = None
        self._setup_players()
        self._setup_ui()

    def _setup_players(self):
        self.accompaniment_player = QMediaPlayer(self)
        self.vocal_player = QMediaPlayer(self)
        self.accompaniment_audio = QAudioOutput(self)
        self.vocal_audio = QAudioOutput(self)
        self.accompaniment_player.setAudioOutput(self.accompaniment_audio)
        self.vocal_player.setAudioOutput(self.vocal_audio)
        self._playback_session = PlaybackSession(
            self.accompaniment_player, self.vocal_player
        )
        self.accompaniment_audio.setVolume(1.0)
        self.vocal_audio.setVolume(1.0)
        self.accompaniment_player.positionChanged.connect(self._position_changed)
        self.vocal_player.positionChanged.connect(self._position_changed)
        self.accompaniment_player.durationChanged.connect(self._duration_changed)
        self.vocal_player.durationChanged.connect(self._duration_changed)
        self.accompaniment_player.playbackStateChanged.connect(self._play_state_changed)
        self.vocal_player.playbackStateChanged.connect(self._play_state_changed)
        self.accompaniment_player.errorOccurred.connect(
            lambda _error, message: self._player_error("伴奏", message)
        )
        self.vocal_player.errorOccurred.connect(
            lambda _error, message: self._player_error("人声", message)
        )
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self._apply_system_audio_output)
        self._apply_system_audio_output()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setMinimumHeight(720)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.content_scroll = scroll

        selected_group = QGroupBox("已选素材")
        selected_layout = QHBoxLayout(selected_group)
        self.selected_song_label = QLabel("尚未从左侧选择素材")
        self.selected_song_label.setWordWrap(True)
        self.selected_song_label.setStyleSheet("font-weight:600;color:#234")
        selected_layout.addWidget(self.selected_song_label)
        root.addWidget(selected_group)

        settings_group = QGroupBox("处理设置")
        settings_layout = QVBoxLayout(settings_group)
        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        self.output_type_combo = QComboBox()
        self.output_type_combo.addItem("人声 + 伴奏（推荐）", "both")
        self.output_type_combo.addItem("仅人声", "vocals")
        self.output_type_combo.addItem("仅伴奏", "accompaniment")
        self.output_type_combo.currentIndexChanged.connect(
            self._update_enhancement_availability
        )
        form.addWidget(QLabel("输出内容"), 0, 0)
        form.addWidget(self.output_type_combo, 0, 1)
        self.format_combo = QComboBox()
        self.format_combo.addItem("WAV（无损）", "wav")
        form.addWidget(QLabel("音频格式"), 0, 2)
        form.addWidget(self.format_combo, 0, 3)

        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("选择输出目录")
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._browse_output)
        form.addWidget(QLabel("输出目录"), 1, 0)
        form.addWidget(self.output_input, 1, 1, 1, 2)
        form.addWidget(browse_button, 1, 3)

        self.denoise_check = QCheckBox("AI 降噪（UVR DeNoise Lite）")
        self.reverb_check = QCheckBox("去回声/混响（UVR DeEcho-DeReverb）")
        form.addWidget(QLabel("增强处理"), 2, 0)
        form.addWidget(self.denoise_check, 2, 1)
        form.addWidget(self.reverb_check, 2, 2, 1, 2)
        settings_layout.addLayout(form)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("▶ 开始处理")
        self.start_button.setMinimumHeight(34)
        self.start_button.clicked.connect(self._start_separation)
        action_row.addWidget(self.start_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_separation)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch()
        settings_layout.addLayout(action_row)
        self.processing_progress = QProgressBar()
        self.processing_progress.setVisible(False)
        settings_layout.addWidget(self.processing_progress)
        self.processing_status = QLabel("")
        self.processing_status.setWordWrap(True)
        self.processing_status.setStyleSheet("color:#555")
        settings_layout.addWidget(self.processing_status)
        root.addWidget(settings_group)

        mixer_group = QGroupBox("音轨试听与调音")
        mixer_layout = QVBoxLayout(mixer_group)
        mixer_layout.setSpacing(7)
        self.current_file_label = QLabel("完成分离后可试听和调节两条音轨")
        self.current_file_label.setStyleSheet("color:#666")
        mixer_layout.addWidget(self.current_file_label)

        transport_row = QHBoxLayout()
        self.pause_button = QPushButton("暂停")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.pause_playback)
        transport_row.addWidget(self.pause_button)
        self.speed_button = QPushButton("倍速 1x")
        self.speed_button.setEnabled(False)
        self.speed_button.clicked.connect(self._cycle_playback_speed)
        transport_row.addWidget(self.speed_button)
        self.reverse_button = QPushButton("倒放")
        self.reverse_button.setEnabled(False)
        self.reverse_button.clicked.connect(self._toggle_reverse_playback)
        transport_row.addWidget(self.reverse_button)
        transport_row.addStretch()
        mixer_layout.addLayout(transport_row)

        mixer_layout.addWidget(QLabel("伴奏"))
        self.accompaniment_waveform = WaveformView("#2A9D9B")
        self.accompaniment_waveform.setMinimumHeight(64)
        self.accompaniment_waveform.setMaximumHeight(90)
        self.accompaniment_waveform.seek_requested.connect(self._seek_to_ratio)
        mixer_layout.addWidget(self.accompaniment_waveform)
        mixer_layout.addWidget(QLabel("人声"))
        self.vocal_waveform = WaveformView("#D97845")
        self.vocal_waveform.setMinimumHeight(64)
        self.vocal_waveform.setMaximumHeight(90)
        self.vocal_waveform.seek_requested.connect(self._seek_to_ratio)
        mixer_layout.addWidget(self.vocal_waveform)

        playback_row = QHBoxLayout()
        self.play_button = QPushButton("▶ 试听")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_playback)
        playback_row.addWidget(self.play_button)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek_slider.sliderReleased.connect(self._seek_released)
        playback_row.addWidget(self.seek_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        playback_row.addWidget(self.time_label)
        mixer_layout.addLayout(playback_row)

        volume_grid = QGridLayout()
        volume_grid.setColumnStretch(1, 1)
        volume_grid.addWidget(QLabel("伴奏音量"), 0, 0)
        self.accompaniment_volume = QSlider(Qt.Orientation.Horizontal)
        self.accompaniment_volume.setRange(0, 100)
        self.accompaniment_volume.setValue(100)
        self.accompaniment_volume.valueChanged.connect(self._volume_changed)
        volume_grid.addWidget(self.accompaniment_volume, 0, 1)
        self.accompaniment_volume_label = QLabel("100%")
        self.accompaniment_volume_label.setMinimumWidth(42)
        volume_grid.addWidget(self.accompaniment_volume_label, 0, 2)

        volume_grid.addWidget(QLabel("人声音量"), 1, 0)
        self.vocal_volume = QSlider(Qt.Orientation.Horizontal)
        self.vocal_volume.setRange(0, 100)
        self.vocal_volume.setValue(100)
        self.vocal_volume.valueChanged.connect(self._volume_changed)
        volume_grid.addWidget(self.vocal_volume, 1, 1)
        self.vocal_volume_label = QLabel("100%")
        self.vocal_volume_label.setMinimumWidth(42)
        volume_grid.addWidget(self.vocal_volume_label, 1, 2)
        mixer_layout.addLayout(volume_grid)

        save_mix_row = QHBoxLayout()
        save_mix_row.addStretch()
        self.save_mix_button = QPushButton("✓ 保存调音结果（伴奏 + 人声）")
        self.save_mix_button.setMinimumHeight(42)
        self.save_mix_button.setMinimumWidth(260)
        self.save_mix_button.setEnabled(False)
        self.save_mix_button.clicked.connect(self._save_mix)
        save_mix_row.addWidget(self.save_mix_button)
        mixer_layout.addLayout(save_mix_row)
        root.addWidget(mixer_group, 1)
        self._update_enhancement_availability()

    def _update_enhancement_availability(self, _index: int = -1):
        vocals_enabled = self.output_type_combo.currentData() != "accompaniment"
        message = (
            "增强模型只作用于人声音轨；仅输出伴奏时不会运行。"
            if not vocals_enabled
            else ""
        )
        for checkbox in (self.denoise_check, self.reverb_check):
            checkbox.setEnabled(vocals_enabled)
        self.denoise_check.setToolTip(message or "去除分离后人声中的持续噪声")
        self.reverb_check.setToolTip(message or "抑制分离后人声中的回声和混响拖尾")

    def set_songs(self, songs: list[dict]):
        self._songs = [song for song in songs if song.get("path")]
        available = {song["path"] for song in self._songs}
        if self._selected_path not in available:
            self._selected_path = self._songs[0]["path"] if self._songs else ""
        self._selected_song_changed()

    def select_song(self, file_path: str):
        if any(song["path"] == file_path for song in self._songs):
            self._selected_path = file_path
            self._selected_song_changed()

    def reload_settings(self):
        """Model and runtime choices are managed by the top-level Model Library."""

    def _selected_song_changed(self):
        file_path = self._selected_path
        self.selected_song_label.setText(
            Path(file_path).name if file_path else "尚未从左侧选择素材"
        )
        if file_path and not self.output_input.text().strip():
            self.output_input.setText(str(Path(file_path).parent / "Separated"))

    def _browse_output(self):
        directory = QFileDialog.getExistingDirectory(
            self, "选择分离结果目录", self.output_input.text().strip()
        )
        if directory:
            self.output_input.setText(directory)

    def _start_separation(self):
        input_path = self._selected_path
        if not input_path:
            QMessageBox.information(self, "人声分离", "请先在素材库中添加并选择音频或视频。")
            return
        if not separation_available():
            QMessageBox.warning(
                self,
                "运行时未安装",
                "当前安装缺少 Demucs 人声分离运行时，请重新安装本地功能依赖。",
            )
            return
        model = (
            getattr(self.config.asr, "vocal_separation_model", "htdemucs")
            if self.config is not None
            else "htdemucs"
        )
        if not separation_model_installed(model):
            reply = QMessageBox.question(
                self,
                "模型尚未安装",
                "所选分离模型尚未下载。是否现在打开模型库？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.model_library_requested.emit()
            return
        requested_enhancements = [
            key
            for key, checked in (
                ("denoise", self.denoise_check.isChecked()),
                ("dereverb", self.reverb_check.isChecked()),
            )
            if checked and self.output_type_combo.currentData() != "accompaniment"
        ]
        missing_enhancements = [
            key for key in requested_enhancements if not enhancement_model_installed(key)
        ]
        if missing_enhancements:
            names = {
                "denoise": "UVR DeNoise Lite",
                "dereverb": "UVR DeEcho-DeReverb",
            }
            reply = QMessageBox.question(
                self,
                "增强模型尚未安装",
                "以下模型尚未下载："
                + "、".join(names[key] for key in missing_enhancements)
                + "。是否现在打开模型库？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.model_library_requested.emit()
            return
        output_dir = self.output_input.text().strip()
        if not output_dir:
            output_dir = str(Path(input_path).parent / "Separated")
            self.output_input.setText(output_dir)
        self._stop_players()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.processing_progress.setVisible(True)
        self.processing_progress.setRange(0, 100)
        self.processing_progress.setValue(0)
        self.processing_status.setText("正在准备处理…")
        self.worker = SeparationWorker(
            input_path,
            output_dir,
            model,
            (
                "cuda"
                if self.config is not None
                and getattr(self.config.asr, "vocal_separation_use_gpu", False)
                else "cpu"
            ),
            self.output_type_combo.currentData(),
            "denoise" in requested_enhancements,
            "dereverb" in requested_enhancements,
            self,
        )
        self.worker.progress.connect(self._show_processing_progress)
        self.worker.completed.connect(self._separation_finished)
        self.worker.start()

    def _show_processing_progress(self, percent: int, message: str):
        self.processing_progress.setValue(percent)
        self.processing_status.setText(message)

    def _cancel_separation(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.processing_status.setText("正在停止当前处理…")

    def _separation_finished(self, success: bool, result: object):
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not success:
            self.processing_status.setText(str(result))
            if "取消" not in str(result):
                QMessageBox.warning(self, "人声分离失败", str(result))
            return
        self._result = result
        self.processing_progress.setValue(100)
        names = [
            path.name
            for path in (result.vocals_path, result.accompaniment_path)
            if path is not None
        ]
        self.processing_status.setText(f"处理完成：{'、'.join(names)}")
        self._load_preview(result)

    def _load_preview(self, result: SeparationResult):
        self._cleanup_reverse_preview()
        self._reverse_mode = False
        self.reverse_button.setText("倒放")
        if result.accompaniment_path is not None:
            self.accompaniment_player.setSource(
                QUrl.fromLocalFile(str(result.accompaniment_path))
            )
            self.accompaniment_waveform.load_wav(str(result.accompaniment_path))
        else:
            self.accompaniment_player.setSource(QUrl())
            self.accompaniment_waveform.samples = []
            self.accompaniment_waveform.update()
        if result.vocals_path is not None:
            self.vocal_player.setSource(QUrl.fromLocalFile(str(result.vocals_path)))
            self.vocal_waveform.load_wav(str(result.vocals_path))
        else:
            self.vocal_player.setSource(QUrl())
            self.vocal_waveform.samples = []
            self.vocal_waveform.update()
        accompaniment_name = (
            result.accompaniment_path.name if result.accompaniment_path else "未输出"
        )
        vocals_name = result.vocals_path.name if result.vocals_path else "未输出"
        self.current_file_label.setText(
            f"伴奏：{accompaniment_name}　人声：{vocals_name}"
        )
        has_accompaniment = result.accompaniment_path is not None
        has_vocals = result.vocals_path is not None
        self.accompaniment_volume.setEnabled(has_accompaniment)
        self.vocal_volume.setEnabled(has_vocals)
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(True)
        self.speed_button.setEnabled(True)
        self.reverse_button.setEnabled(True)
        self.seek_slider.setEnabled(True)
        self.save_mix_button.setEnabled(has_accompaniment and has_vocals)
        self.save_mix_button.setToolTip(
            "" if has_accompaniment and has_vocals else "保存调音结果需要同时输出人声和伴奏"
        )
        self._apply_system_audio_output()
        self._volume_changed()

    def _toggle_playback(self):
        is_playing = any(
            player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            for player in (self.accompaniment_player, self.vocal_player)
        )
        if is_playing:
            self.accompaniment_player.pause()
            self.vocal_player.pause()
        else:
            if not self._apply_system_audio_output():
                self.processing_status.setText(
                    "未检测到音频输出设备，请检查 Windows 声音设置。"
                )
                return
            self._volume_changed()
            master = (
                self.accompaniment_player
                if self._result and self._result.accompaniment_path is not None
                else self.vocal_player
            )
            position = master.position()
            self.vocal_player.setPosition(position)
            players = tuple(
                player
                for player, path in (
                    (self.vocal_player, self._result.vocals_path if self._result else None),
                    (
                        self.accompaniment_player,
                        self._result.accompaniment_path if self._result else None,
                    ),
                )
                if path is not None
            )
            self._playback_session.play_all(players)
            track_count = sum(
                path is not None
                for path in (
                    self._result.vocals_path,
                    self._result.accompaniment_path,
                )
            )
            self.processing_status.setText(
                f"正在通过 Windows 系统默认输出播放{track_count}条音轨。"
            )
            self.playback_started.emit()

    def _stop_players(self):
        self.accompaniment_player.stop()
        self.vocal_player.stop()

    def pause_playback(self):
        self.accompaniment_player.pause()
        self.vocal_player.pause()

    def _master_player(self):
        return (
            self.accompaniment_player
            if self._result and self._result.accompaniment_path is not None
            else self.vocal_player
        )

    def _display_position(self, media_position: int | None = None) -> int:
        master = self._master_player()
        position = master.position() if media_position is None else media_position
        duration = master.duration()
        return max(0, duration - position) if self._reverse_mode else position

    def _media_position(self, display_position: int) -> int:
        duration = self._master_player().duration()
        return (
            max(0, duration - display_position)
            if self._reverse_mode
            else display_position
        )

    def _cycle_playback_speed(self):
        self._playback_speed = (
            self._playback_speed + 1 if self._playback_speed < 10 else 1
        )
        for player in (self.accompaniment_player, self.vocal_player):
            player.setPlaybackRate(float(self._playback_speed))
        self.speed_button.setText(f"倍速 {self._playback_speed}x")

    def _toggle_reverse_playback(self):
        if self._result is None:
            return
        if self._reverse_paths:
            self._activate_reverse_mode(not self._reverse_mode)
            return
        sources = {
            name: path
            for name, path in {
                "accompaniment": self._result.accompaniment_path,
                "vocals": self._result.vocals_path,
            }.items()
            if path is not None
        }
        self._reverse_temp_dir = tempfile.mkdtemp(prefix="echovault_reverse_preview_")
        self.reverse_button.setEnabled(False)
        self.processing_status.setText("正在生成倒放试听音轨…")
        self.reverse_worker = ReversePreviewWorker(
            sources, self._reverse_temp_dir, self
        )
        self.reverse_worker.completed.connect(self._reverse_preview_ready)
        self.reverse_worker.start()

    def _reverse_preview_ready(self, success: bool, result: object):
        self.reverse_button.setEnabled(True)
        if not success:
            self.processing_status.setText(str(result))
            QMessageBox.warning(self, "倒放准备失败", str(result))
            return
        self._reverse_paths = result
        self._activate_reverse_mode(True)

    def _activate_reverse_mode(self, enabled: bool):
        if self._result is None:
            return
        was_playing = any(
            player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            for player in (self.accompaniment_player, self.vocal_player)
        )
        display_position = self._display_position()
        self.pause_playback()
        self._reverse_mode = enabled
        accompaniment = (
            self._reverse_paths.get("accompaniment")
            if enabled
            else self._result.accompaniment_path
        )
        vocals = (
            self._reverse_paths.get("vocals") if enabled else self._result.vocals_path
        )
        self.accompaniment_player.setSource(
            QUrl.fromLocalFile(str(accompaniment)) if accompaniment else QUrl()
        )
        self.vocal_player.setSource(
            QUrl.fromLocalFile(str(vocals)) if vocals else QUrl()
        )
        self.reverse_button.setText("恢复正放" if enabled else "倒放")
        self.processing_status.setText("倒放模式" if enabled else "正放模式")

        def restore_position():
            media_position = self._media_position(display_position)
            self.accompaniment_player.setPosition(media_position)
            self.vocal_player.setPosition(media_position)
            for player in (self.accompaniment_player, self.vocal_player):
                player.setPlaybackRate(float(self._playback_speed))
            if was_playing:
                self._toggle_playback()

        QTimer.singleShot(120, restore_position)

    def _cleanup_reverse_preview(self):
        self._reverse_paths = {}
        if self._reverse_temp_dir:
            shutil.rmtree(self._reverse_temp_dir, ignore_errors=True)
            self._reverse_temp_dir = None

    def closeEvent(self, event):
        self._cleanup_reverse_preview()
        super().closeEvent(event)

    def _apply_system_audio_output(self):
        if not hasattr(self, "accompaniment_audio"):
            return False
        available = apply_system_default_audio(
            self.accompaniment_audio, self.vocal_audio
        )
        if hasattr(self, "accompaniment_volume"):
            self._volume_changed()
        return available

    def _player_error(self, track: str, message: str):
        self.processing_status.setText(
            f"{track}播放器错误：{message or '无法播放当前音轨'}"
        )

    def _play_state_changed(self, state):
        playing = any(
            player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            for player in (self.accompaniment_player, self.vocal_player)
        )
        self.play_button.setText(
            "❚❚ 暂停" if playing else "▶ 试听"
        )

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _position_changed(self, position: int):
        if (
            self.sender() is self.vocal_player
            and self._result is not None
            and self._result.accompaniment_path is not None
        ):
            return
        master = self._master_player()
        duration = master.duration()
        display_position = self._display_position(position)
        if duration > 0:
            ratio = display_position / duration
            if not self._seeking:
                self.seek_slider.setValue(int(ratio * 1000))
            self.accompaniment_waveform.set_playhead(ratio)
            self.vocal_waveform.set_playhead(ratio)
        self.time_label.setText(
            f"{self._format_time(display_position)} / {self._format_time(duration)}"
        )
        self.position_changed_ms.emit(display_position)
        if (
            self._result is not None
            and self._result.vocals_path is not None
            and self.vocal_player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
            and abs(self.vocal_player.position() - position) > 120
        ):
            self.vocal_player.setPosition(position)

    def _duration_changed(self, duration: int):
        if (
            self.sender() is self.vocal_player
            and self._result is not None
            and self._result.accompaniment_path is not None
        ):
            return
        self.time_label.setText(f"00:00 / {self._format_time(duration)}")

    def _seek_released(self):
        self._seeking = False
        master = self._master_player()
        duration = master.duration()
        display_position = int(duration * self.seek_slider.value() / 1000)
        media_position = self._media_position(display_position)
        self.accompaniment_player.setPosition(media_position)
        self.vocal_player.setPosition(media_position)

    def _seek_to_ratio(self, ratio: float):
        if self._result is None:
            return
        duration = self._master_player().duration()
        if duration <= 0:
            return
        display_position = int(duration * ratio)
        media_position = self._media_position(display_position)
        self.accompaniment_player.setPosition(media_position)
        self.vocal_player.setPosition(media_position)
        self.seek_slider.setValue(int(ratio * 1000))
        self.accompaniment_waveform.set_playhead(ratio)
        self.vocal_waveform.set_playhead(ratio)
        self.time_label.setText(
            f"{self._format_time(display_position)} / {self._format_time(duration)}"
        )
        self.position_changed_ms.emit(display_position)

    def _volume_changed(self, _value: int = -1):
        accompaniment = self.accompaniment_volume.value()
        vocals = self.vocal_volume.value()
        self.accompaniment_audio.setVolume(accompaniment / 100)
        self.vocal_audio.setVolume(vocals / 100)
        self.accompaniment_volume_label.setText(f"{accompaniment}%")
        self.vocal_volume_label.setText(f"{vocals}%")

    def _save_mix(self):
        if (
            self._result is None
            or self._result.vocals_path is None
            or self._result.accompaniment_path is None
        ):
            return
        default_path = self._result.accompaniment_path.with_name(
            f"{self._result.accompaniment_path.stem.removesuffix('_accompaniment')}_mixed.wav"
        )
        output_path, _selected_filter = QFileDialog.getSaveFileName(
            self, "保存调音结果", str(default_path), "WAV 音频 (*.wav)"
        )
        if not output_path:
            return
        self.save_mix_button.setEnabled(False)
        self.processing_status.setText("正在保存调音结果…")
        self.mix_worker = MixExportWorker(
            str(self._result.vocals_path),
            str(self._result.accompaniment_path),
            output_path,
            self.vocal_volume.value(),
            self.accompaniment_volume.value(),
            self,
        )
        self.mix_worker.completed.connect(self._mix_finished)
        self.mix_worker.start()

    def _mix_finished(self, success: bool, message: str):
        self.save_mix_button.setEnabled(True)
        if success:
            self.processing_status.setText(f"调音结果已保存：{message}")
            QMessageBox.information(self, "保存完成", f"调音结果已保存：\n{message}")
        else:
            self.processing_status.setText(message)
            QMessageBox.warning(self, "保存失败", message)
