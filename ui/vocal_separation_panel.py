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

from core.vocal_separation import (
    SEPARATION_MODELS,
    SeparationCancelled,
    SeparationResult,
    export_stem,
    mix_stems,
    recommended_device,
    separate_vocals,
    separation_available,
    separation_model_installed,
)
from ui.audio_device_combo import AudioDeviceCombo
from ui.model_library_dialog import ModelLibraryDialog


class SeparationWorker(QThread):
    progress = pyqtSignal(int, str)
    completed = pyqtSignal(bool, object)

    def __init__(self, input_path: str, output_dir: str, model: str, device: str, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.output_dir = output_dir
        self.model = model
        self.device = device

    def run(self):
        try:
            result = separate_vocals(
                self.input_path,
                self.output_dir,
                model=self.model,
                device=self.device,
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


class StemExportWorker(QThread):
    completed = pyqtSignal(bool, str)

    def __init__(self, source_path: str, output_path: str, parent=None):
        super().__init__(parent)
        self.source_path = source_path
        self.output_path = output_path

    def run(self):
        try:
            result = export_stem(self.source_path, self.output_path)
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

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._songs: list[dict] = []
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
        self.accompaniment_player.durationChanged.connect(self._duration_changed)
        self.accompaniment_player.playbackStateChanged.connect(self._play_state_changed)
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
        self.song_combo = QComboBox()
        self.song_combo.currentIndexChanged.connect(self._song_changed)
        form.addRow("处理素材:", self.song_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("分离原声人声与伴奏", "separate")
        form.addRow("处理模式:", self.mode_combo)
        self.output_type_combo = QComboBox()
        self.output_type_combo.addItem("人声 + 伴奏（推荐）", "both")
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

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        for spec in SEPARATION_MODELS.values():
            self.model_combo.addItem(spec.name, spec.key)
        model_row.addWidget(self.model_combo, 1)
        library_button = QPushButton("模型库")
        library_button.clicked.connect(self._open_model_library)
        model_row.addWidget(library_button)
        form.addRow("分离模型:", model_row)

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
        self.save_accompaniment_button = QPushButton("单独保存伴奏")
        self.save_accompaniment_button.setEnabled(False)
        self.save_accompaniment_button.clicked.connect(
            lambda: self._save_stem("accompaniment")
        )
        volume_grid.addWidget(self.save_accompaniment_button, 0, 3)

        volume_grid.addWidget(QLabel("人声音量"), 1, 0)
        self.vocal_volume = QSlider(Qt.Orientation.Horizontal)
        self.vocal_volume.setRange(0, 100)
        self.vocal_volume.setValue(100)
        self.vocal_volume.valueChanged.connect(self._volume_changed)
        volume_grid.addWidget(self.vocal_volume, 1, 1)
        self.vocal_volume_label = QLabel("100%")
        self.vocal_volume_label.setMinimumWidth(42)
        volume_grid.addWidget(self.vocal_volume_label, 1, 2)
        self.save_vocal_button = QPushButton("单独保存人声")
        self.save_vocal_button.setEnabled(False)
        self.save_vocal_button.clicked.connect(lambda: self._save_stem("vocals"))
        volume_grid.addWidget(self.save_vocal_button, 1, 3)
        mixer_layout.addLayout(volume_grid)

        save_mix_row = QHBoxLayout()
        save_mix_row.addStretch()
        self.save_mix_button = QPushButton("✓ 保存调音结果（伴奏 + 人声）")
        self.save_mix_button.setEnabled(False)
        self.save_mix_button.clicked.connect(self._save_mix)
        save_mix_row.addWidget(self.save_mix_button)
        mixer_layout.addLayout(save_mix_row)
        splitter.addWidget(mixer_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 360])

    def set_songs(self, songs: list[dict]):
        current_path = self.song_combo.currentData()
        self._songs = [song for song in songs if song.get("path")]
        self.song_combo.blockSignals(True)
        self.song_combo.clear()
        for song in self._songs:
            self.song_combo.addItem(song.get("name") or Path(song["path"]).name, song["path"])
        index = self.song_combo.findData(current_path)
        self.song_combo.setCurrentIndex(index if index >= 0 else (0 if self._songs else -1))
        self.song_combo.blockSignals(False)
        self._song_changed()

    def select_song(self, file_path: str):
        index = self.song_combo.findData(file_path)
        if index >= 0:
            self.song_combo.setCurrentIndex(index)

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

    def _song_changed(self, _index: int = -1):
        file_path = self.song_combo.currentData()
        if file_path and not self.output_input.text().strip():
            self.output_input.setText(str(Path(file_path).parent / "Separated"))

    def _browse_output(self):
        directory = QFileDialog.getExistingDirectory(
            self, "选择分离结果目录", self.output_input.text().strip()
        )
        if directory:
            self.output_input.setText(directory)

    def _open_model_library(self):
        dialog = ModelLibraryDialog(self, initial_category="separation")
        dialog.exec()

    def _start_separation(self):
        input_path = self.song_combo.currentData()
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
                self._open_model_library()
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
        self.processing_status.setText(
            f"处理完成：{result.vocals_path.name}、{result.accompaniment_path.name}"
        )
        self._load_preview(result)

    def _load_preview(self, result: SeparationResult):
        self.accompaniment_player.setSource(QUrl.fromLocalFile(str(result.accompaniment_path)))
        self.vocal_player.setSource(QUrl.fromLocalFile(str(result.vocals_path)))
        self.accompaniment_waveform.load_wav(str(result.accompaniment_path))
        self.vocal_waveform.load_wav(str(result.vocals_path))
        self.current_file_label.setText(
            f"伴奏：{result.accompaniment_path.name}　人声：{result.vocals_path.name}"
        )
        self.play_button.setEnabled(True)
        self.seek_slider.setEnabled(True)
        self.save_mix_button.setEnabled(True)
        self.save_accompaniment_button.setEnabled(True)
        self.save_vocal_button.setEnabled(True)
        self._apply_audio_device()
        self._volume_changed()

    def _toggle_playback(self):
        if self.accompaniment_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
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
            position = self.accompaniment_player.position()
            self.vocal_player.setPosition(position)
            self.vocal_player.play()
            self.accompaniment_player.play()
            self.processing_status.setText(
                f"正在通过“{self.audio_device_combo.currentText()}”播放两条音轨。"
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
        self.play_button.setText(
            "❚❚ 暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ 试听"
        )

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _position_changed(self, position: int):
        duration = self.accompaniment_player.duration()
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
            self.vocal_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and abs(self.vocal_player.position() - position) > 120
        ):
            self.vocal_player.setPosition(position)

    def _duration_changed(self, duration: int):
        self.time_label.setText(f"00:00 / {self._format_time(duration)}")

    def _seek_released(self):
        self._seeking = False
        duration = self.accompaniment_player.duration()
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
        if self._result is None:
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

    def _save_stem(self, stem: str):
        if self._result is None:
            return
        is_vocal = stem == "vocals"
        source = self._result.vocals_path if is_vocal else self._result.accompaniment_path
        title = "保存人声音轨" if is_vocal else "保存伴奏音轨"
        output_path, _selected_filter = QFileDialog.getSaveFileName(
            self, title, str(source), "WAV 音频 (*.wav)"
        )
        if not output_path:
            return
        self.save_accompaniment_button.setEnabled(False)
        self.save_vocal_button.setEnabled(False)
        self.processing_status.setText(f"正在{title}…")
        self.stem_worker = StemExportWorker(str(source), output_path, self)
        self.stem_worker.completed.connect(self._stem_finished)
        self.stem_worker.start()

    def _stem_finished(self, success: bool, message: str):
        self.save_accompaniment_button.setEnabled(self._result is not None)
        self.save_vocal_button.setEnabled(self._result is not None)
        if success:
            self.processing_status.setText(f"分离音轨已保存：{message}")
            QMessageBox.information(self, "保存完成", f"分离音轨已保存：\n{message}")
        else:
            self.processing_status.setText(message)
            QMessageBox.warning(self, "保存失败", message)

    def _mix_finished(self, success: bool, message: str):
        self.save_mix_button.setEnabled(True)
        if success:
            self.processing_status.setText(f"调音结果已保存：{message}")
            QMessageBox.information(self, "保存完成", f"调音结果已保存：\n{message}")
        else:
            self.processing_status.setText(message)
            QMessageBox.warning(self, "保存失败", message)
