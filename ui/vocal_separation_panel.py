"""Right-side vocal separation workspace with a two-track preview mixer."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.config import config_manager
from core.vocal_separation import (
    SEPARATION_MODELS,
    SeparationCancelled,
    SeparationResult,
    mix_stems,
    recommended_device,
    separate_vocals,
    separation_available,
    separation_model_installed,
)
from ui.audio_device_combo import AudioDeviceCombo


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
        parent=None,
    ):
        super().__init__(parent)
        self.input_path = input_path
        self.output_dir = output_dir
        self.model = model
        self.device = device
        self.output_content = output_content

    def run(self):
        try:
            result = separate_vocals(
                self.input_path,
                self.output_dir,
                model=self.model,
                device=self.device,
                output_content=self.output_content,
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


class WaveformView(QWidget):
    """Small dependency-free WAV overview with a shared playhead."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.samples: list[float] = []
        self.playhead = 0.0
        self.setMinimumHeight(76)

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

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._songs: list[dict] = []
        self._selected_path = ""
        self._result: SeparationResult | None = None
        self._seeking = False
        self._setup_players()
        self._setup_ui()

    def _setup_players(self):
        self.accompaniment_player = QMediaPlayer(self)
        self.vocal_player = QMediaPlayer(self)
        self.accompaniment_audio = QAudioOutput(self)
        self.vocal_audio = QAudioOutput(self)
        self.accompaniment_player.setAudioOutput(self.accompaniment_audio)
        self.vocal_player.setAudioOutput(self.vocal_audio)
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

    def _setup_ui(self):
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter)

        settings_group = QGroupBox("处理设置")
        form = QFormLayout(settings_group)
        self.output_type_combo = QComboBox()
        self.output_type_combo.addItem("人声 + 伴奏（推荐）", "both")
        self.output_type_combo.addItem("仅人声", "vocals")
        self.output_type_combo.addItem("仅伴奏", "accompaniment")
        form.addRow("输出内容:", self.output_type_combo)
        self.format_combo = QComboBox()
        self.format_combo.addItem("WAV（无损）", "wav")
        form.addRow("音频格式:", self.format_combo)

        output_row = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("选择输出目录")
        output_row.addWidget(self.output_input, 1)
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._browse_output)
        output_row.addWidget(browse_button)
        form.addRow("输出目录:", output_row)

        self.model_combo = QComboBox()
        for spec in SEPARATION_MODELS.values():
            self.model_combo.addItem(spec.name, spec.key)
        self.model_combo.currentIndexChanged.connect(self._save_preferences)
        form.addRow("分离模型:", self.model_combo)

        self.denoise_check = QCheckBox("降噪（模型尚未接入）")
        self.denoise_check.setEnabled(False)
        form.addRow("增强处理:", self.denoise_check)
        self.reverb_check = QCheckBox("混响移除（模型尚未接入）")
        self.reverb_check.setEnabled(False)
        form.addRow("", self.reverb_check)

        self.device_combo = QComboBox()
        self.device_combo.addItem("CPU（通用）", "cpu")
        if recommended_device() == "cuda":
            self.device_combo.insertItem(0, "NVIDIA CUDA（推荐）", "cuda")
        self.device_combo.currentIndexChanged.connect(self._save_preferences)
        form.addRow("硬件加速:", self.device_combo)
        self.reload_settings()

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
        form.addRow("", action_row)
        self.processing_progress = QProgressBar()
        self.processing_progress.setVisible(False)
        form.addRow("处理进度:", self.processing_progress)
        self.processing_status = QLabel("")
        self.processing_status.setWordWrap(True)
        self.processing_status.setStyleSheet("color:#555")
        form.addRow("", self.processing_status)
        splitter.addWidget(settings_group)

        mixer_group = QGroupBox("音量调节台")
        mixer_layout = QVBoxLayout(mixer_group)
        self.current_file_label = QLabel("完成分离后可试听和调节两条音轨")
        self.current_file_label.setStyleSheet("color:#666")
        mixer_layout.addWidget(self.current_file_label)
        mixer_layout.addWidget(QLabel("伴奏"))
        self.accompaniment_waveform = WaveformView("#2A9D9B")
        mixer_layout.addWidget(self.accompaniment_waveform)
        mixer_layout.addWidget(QLabel("人声"))
        self.vocal_waveform = WaveformView("#D97845")
        mixer_layout.addWidget(self.vocal_waveform)

        playback_row = QHBoxLayout()
        self.play_button = QPushButton("▶ 试听")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_playback)
        playback_row.addWidget(self.play_button)
        playback_row.addWidget(QLabel("输出:"))
        self.audio_device_combo = AudioDeviceCombo()
        self.audio_device_combo.device_changed.connect(self._apply_audio_device)
        playback_row.addWidget(self.audio_device_combo)
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
        splitter.addWidget(mixer_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 360])

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
        if not hasattr(self, "model_combo") or self.config is None:
            return
        model = getattr(self.config.asr, "vocal_separation_model", "htdemucs")
        model_index = self.model_combo.findData(model)
        self.model_combo.setCurrentIndex(max(0, model_index))
        wants_gpu = bool(
            getattr(self.config.asr, "vocal_separation_use_gpu", False)
        )
        device_index = self.device_combo.findData("cuda" if wants_gpu else "cpu")
        self.device_combo.setCurrentIndex(max(0, device_index))

    def _save_preferences(self, _index: int = -1):
        if self.config is None:
            return
        self.config.asr.vocal_separation_model = self.model_combo.currentData()
        self.config.asr.vocal_separation_use_gpu = (
            self.device_combo.currentData() == "cuda"
        )
        config_manager.config = self.config
        config_manager.save()

    def _selected_song_changed(self):
        file_path = self._selected_path
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
        model = self.model_combo.currentData()
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
            self.device_combo.currentData(),
            self.output_type_combo.currentData(),
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
        self.seek_slider.setEnabled(True)
        self.save_mix_button.setEnabled(has_accompaniment and has_vocals)
        self.save_mix_button.setToolTip(
            "" if has_accompaniment and has_vocals else "保存调音结果需要同时输出人声和伴奏"
        )
        self._apply_audio_device()
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
            if not self.audio_device_combo.apply_to(
                self.accompaniment_audio, self.vocal_audio
            ):
                self.processing_status.setText(
                    "未检测到音频输出设备，请检查 Windows 声音设置。"
                )
                return
            self.accompaniment_audio.setMuted(False)
            self.vocal_audio.setMuted(False)
            self._volume_changed()
            master = (
                self.accompaniment_player
                if self._result and self._result.accompaniment_path is not None
                else self.vocal_player
            )
            position = master.position()
            self.vocal_player.setPosition(position)
            if self._result and self._result.vocals_path is not None:
                self.vocal_player.play()
            if self._result and self._result.accompaniment_path is not None:
                self.accompaniment_player.play()
            track_count = sum(
                path is not None
                for path in (
                    self._result.vocals_path,
                    self._result.accompaniment_path,
                )
            )
            self.processing_status.setText(
                f"正在通过“{self.audio_device_combo.currentText()}”播放{track_count}条音轨。"
            )

    def _stop_players(self):
        self.accompaniment_player.stop()
        self.vocal_player.stop()

    def _apply_audio_device(self, _device=None):
        if not hasattr(self, "audio_device_combo"):
            return
        self.audio_device_combo.apply_to(
            self.accompaniment_audio, self.vocal_audio
        )
        self._volume_changed()

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
        master = (
            self.accompaniment_player
            if self._result and self._result.accompaniment_path is not None
            else self.vocal_player
        )
        duration = master.duration()
        if duration > 0:
            ratio = position / duration
            if not self._seeking:
                self.seek_slider.setValue(int(ratio * 1000))
            self.accompaniment_waveform.set_playhead(ratio)
            self.vocal_waveform.set_playhead(ratio)
        self.time_label.setText(
            f"{self._format_time(position)} / {self._format_time(duration)}"
        )
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
        master = (
            self.accompaniment_player
            if self._result and self._result.accompaniment_path is not None
            else self.vocal_player
        )
        duration = master.duration()
        position = int(duration * self.seek_slider.value() / 1000)
        self.accompaniment_player.setPosition(position)
        self.vocal_player.setPosition(position)

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
