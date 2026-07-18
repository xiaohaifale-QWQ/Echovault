"""Task-specific audio workspaces inspired by mature mobile audio editors."""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.metadata import read_tags
from ui.audio_timeline import AudioTimeline


class ValueSlider(QWidget):
    """A compact labelled slider with an exact numeric control."""

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        value: float,
        *,
        step: float = 1.0,
        suffix: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._step = float(step)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel(label)
        title.setMinimumWidth(78)
        title.setObjectName("controlLabel")
        layout.addWidget(title)
        minus = QPushButton("−")
        minus.setObjectName("roundStepButton")
        minus.setFixedSize(28, 28)
        layout.addWidget(minus)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(minimum / self._step), round(maximum / self._step))
        self.slider.setValue(round(value / self._step))
        layout.addWidget(self.slider, 1)
        plus = QPushButton("+")
        plus.setObjectName("roundStepButton")
        plus.setFixedSize(28, 28)
        layout.addWidget(plus)
        self.spin = QDoubleSpinBox()
        decimals = 0 if self._step >= 1 else max(1, len(str(self._step).split(".")[-1]))
        self.spin.setDecimals(decimals)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(self._step)
        self.spin.setValue(value)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(92)
        layout.addWidget(self.spin)
        minus.clicked.connect(lambda: self.spin.setValue(self.spin.value() - self._step))
        plus.clicked.connect(lambda: self.spin.setValue(self.spin.value() + self._step))
        self.slider.valueChanged.connect(lambda raw: self.spin.setValue(float(raw) * self._step))
        self.spin.valueChanged.connect(self._spin_changed)

    def _spin_changed(self, value: float):
        self.slider.blockSignals(True)
        self.slider.setValue(round(value / self._step))
        self.slider.blockSignals(False)
        self.valueChanged.emit(value)

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, value: float):
        self.spin.setValue(value)


class EqualizerBand(QWidget):
    def __init__(self, frequency: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        self.value_label = QLabel("+0.0")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setObjectName("eqValue")
        layout.addWidget(self.value_label)
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(-120, 120)
        self.slider.setValue(0)
        self.slider.setTickInterval(30)
        self.slider.setMinimumHeight(190)
        self.slider.valueChanged.connect(
            lambda value: self.value_label.setText(f"{value / 10:+.1f}")
        )
        layout.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        label = QLabel(frequency)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    def value(self) -> float:
        return self.slider.value() / 10.0

    def setValue(self, value: float):
        self.slider.setValue(round(value * 10))


class MiniWaveform(QWidget):
    """Compact track clip used by the multitrack workspaces."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.seed = sum(ord(character) for character in path) % 31 + 5
        self._cached_path: QPainterPath | None = None
        self._cached_size = None
        self.setMinimumHeight(46)
        self.setMinimumWidth(240)

    def _waveform_path(self) -> QPainterPath:
        if self._cached_path is not None and self._cached_size == self.size():
            return self._cached_path
        center = self.height() / 2
        path = QPainterPath()
        points: list[QPointF] = []
        for index in range(100):
            x = index * self.width() / 99
            wave = abs(
                math.sin((index + self.seed) * 0.31) + 0.45 * math.sin((index + self.seed) * 0.83)
            )
            amplitude = min(1.0, 0.18 + wave * 0.55) * (self.height() / 2 - 5)
            points.append(QPointF(x, center - amplitude))
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        for index in range(99, -1, -1):
            x = index * self.width() / 99
            top = points[index].y()
            path.lineTo(QPointF(x, center + (center - top)))
        path.closeSubpath()
        self._cached_path = path
        self._cached_size = self.size()
        return path

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#E8F4F2"))
        path = self._waveform_path()
        painter.fillPath(path, QColor("#42AFA1"))


class TrackRow(QFrame):
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, path: str, index: int, parent=None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("trackRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(7)
        self.index_label = QLabel(f"轨道 {index + 1}")
        self.index_label.setMinimumWidth(52)
        self.index_label.setObjectName("trackIndex")
        layout.addWidget(self.index_label)
        self.mute = QPushButton("M")
        self.solo = QPushButton("S")
        for button in (self.mute, self.solo):
            button.setCheckable(True)
            button.setObjectName("trackToggle")
            button.setFixedSize(28, 28)
            layout.addWidget(button)
        name = QLabel(Path(path).name)
        name.setToolTip(path)
        name.setMinimumWidth(120)
        layout.addWidget(name)
        layout.addWidget(MiniWaveform(path), 1)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 200)
        self.volume.setValue(100)
        self.volume.setMaximumWidth(150)
        layout.addWidget(self.volume)
        self.volume_label = QLabel("100%")
        self.volume_label.setMinimumWidth(42)
        layout.addWidget(self.volume_label)
        remove = QPushButton("删除")
        remove.setObjectName("quietDanger")
        layout.addWidget(remove)
        self.volume.valueChanged.connect(
            lambda value: (self.volume_label.setText(f"{value}%"), self.changed.emit())
        )
        self.mute.toggled.connect(self.changed)
        self.solo.toggled.connect(self.changed)
        remove.clicked.connect(lambda: self.remove_requested.emit(self))

    def effective_volume(self) -> float:
        return 0.0 if self.mute.isChecked() else self.volume.value() / 100.0


class TrackEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[TrackRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(6)
        layout.addLayout(self.rows_layout)
        self.empty = QLabel("点击“添加轨道”建立多轨工程")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("emptyTrackHint")
        self.empty.setMinimumHeight(120)
        layout.addWidget(self.empty)
        layout.addStretch()

    def set_paths(self, paths: list[str]):
        while self.rows:
            self._remove_row(self.rows[-1], emit=False)
        for path in paths:
            self.add_path(path, emit=False)
        self._refresh()

    def add_path(self, path: str, *, emit=True):
        if not path or path in self.paths():
            return
        row = TrackRow(path, len(self.rows), self)
        row.changed.connect(self.changed)
        row.remove_requested.connect(self._remove_row)
        self.rows.append(row)
        self.rows_layout.addWidget(row)
        self._refresh()
        if emit:
            self.changed.emit()

    def _remove_row(self, row: TrackRow, *, emit=True):
        if row not in self.rows:
            return
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh()
        if emit:
            self.changed.emit()

    def _refresh(self):
        self.empty.setVisible(not self.rows)
        for index, row in enumerate(self.rows):
            row.index_label.setText(f"轨道 {index + 1}")

    def paths(self) -> list[str]:
        return [row.path for row in self.rows]

    def volumes(self) -> list[float]:
        soloed = [row for row in self.rows if row.solo.isChecked()]
        return [row.effective_volume() if not soloed or row in soloed else 0.0 for row in self.rows]


class AudioToolWorkspace(QWidget):
    """One complete, tool-specific editing workflow."""

    run_requested = pyqtSignal(object)
    play_requested = pyqtSignal()
    result_play_requested = pyqtSignal()
    result_open_requested = pyqtSignal()
    seek_requested = pyqtSignal(float)
    selection_requested = pyqtSignal(float, float)

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.fields: dict[str, QWidget] = {}
        self.timelines: list[AudioTimeline] = []
        self._selection = (0.0, 0.0)
        self._duration = 0.0
        self._path = ""
        self._building_selection = False
        self._result_path = ""
        self.track_editor: TrackEditor | None = None
        self.input_edit = QLineEdit()
        self.input_edit.hide()
        self.output_edit = QLineEdit()
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        surface = QFrame()
        surface.setObjectName("toolWorkspaceSurface")
        self.body = QVBoxLayout(surface)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(12)
        self._build_header()
        builder = getattr(self, f"_build_{self.spec.key}", self._build_generic)
        builder()
        self._build_output()
        scroll.setWidget(surface)
        outer.addWidget(scroll)
        self.setStyleSheet(self._style())

    def _build_header(self):
        row = QHBoxLayout()
        title_box = QVBoxLayout()
        heading = QLabel(self.spec.title)
        heading.setObjectName("workspaceTitle")
        title_box.addWidget(heading)
        note = QLabel(self.spec.description)
        note.setWordWrap(True)
        note.setObjectName("workspaceDescription")
        title_box.addWidget(note)
        row.addLayout(title_box, 1)
        self.source_label = QLabel("尚未选择素材")
        self.source_label.setObjectName("sourceChip")
        row.addWidget(self.source_label)
        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("workspacePlay")
        self.play_button.clicked.connect(self.play_requested)
        row.addWidget(self.play_button)
        self.body.addLayout(row)

    def _new_timeline(self, *, height=220, interactive=True, color="#4A90D9"):
        timeline = AudioTimeline()
        timeline.setMinimumHeight(height)
        timeline.setMaximumHeight(height)
        timeline.set_interaction_enabled(interactive)
        timeline.set_waveform_color(color)
        if interactive:
            timeline.seek_requested.connect(self.seek_requested)
            timeline.selection_changed.connect(self._timeline_selection_changed)
        self.timelines.append(timeline)
        return timeline

    def _zoom_row(self, timeline: AudioTimeline):
        row = QHBoxLayout()
        row.addStretch()
        for label, handler in (
            ("缩小", lambda: timeline.zoom(1.5)),
            ("放大", lambda: timeline.zoom(0.65)),
            ("适合选区", timeline.zoom_to_selection),
            ("显示全部", timeline.show_all),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            row.addWidget(button)
        return row

    def _build_trim(self):
        status = QHBoxLayout()
        self.position_label = QLabel("位置  0:00.000 / 0:00.000")
        self.position_label.setObjectName("positionReadout")
        status.addWidget(self.position_label)
        status.addStretch()
        self.selection_label = QLabel("已选  0:00.000")
        self.selection_label.setObjectName("selectionReadout")
        status.addWidget(self.selection_label)
        self.body.addLayout(status)
        self.timeline = self._new_timeline(height=250)
        self.body.addWidget(self.timeline)
        self.body.addLayout(self._zoom_row(self.timeline))

        selection = QGroupBox("精确选区")
        grid = QGridLayout(selection)
        self.selection_start = self._time_spin()
        self.selection_end = self._time_spin()
        self.selection_start.valueChanged.connect(self._selection_fields_changed)
        self.selection_end.valueChanged.connect(self._selection_fields_changed)
        grid.addWidget(QLabel("开始时间"), 0, 0)
        grid.addWidget(self.selection_start, 0, 1)
        set_start = QPushButton("设为游标位置")
        set_start.clicked.connect(
            lambda: self.selection_start.setValue(self.timeline.playhead_seconds)
        )
        grid.addWidget(set_start, 0, 2)
        grid.addWidget(QLabel("结束时间"), 1, 0)
        grid.addWidget(self.selection_end, 1, 1)
        set_end = QPushButton("设为游标位置")
        set_end.clicked.connect(lambda: self.selection_end.setValue(self.timeline.playhead_seconds))
        grid.addWidget(set_end, 1, 2)
        select_all = QPushButton("全选")
        select_all.clicked.connect(self.timeline.select_all)
        clear = QPushButton("重置选区")
        clear.clicked.connect(self.timeline.clear_selection)
        grid.addWidget(select_all, 0, 3)
        grid.addWidget(clear, 1, 3)
        self.body.addWidget(selection)

        controls = QGroupBox("片段处理")
        controls_layout = QGridLayout(controls)
        definitions = (
            ("gain_db", "音量增益", -24, 24, 0, 0.5, " dB"),
            ("speed", "速度", 0.25, 4, 1, 0.05, " ×"),
            ("semitones", "变调", -12, 12, 0, 1, " 半音"),
            ("delay", "延迟", 0, 10, 0, 0.1, " 秒"),
            ("fade_in", "淡入", 0, 30, 0, 0.1, " 秒"),
            ("fade_out", "淡出", 0, 30, 0, 0.1, " 秒"),
        )
        for index, definition in enumerate(definitions):
            key, label, minimum, maximum, value, step, suffix = definition
            widget = ValueSlider(label, minimum, maximum, value, step=step, suffix=suffix)
            self.fields[key] = widget
            controls_layout.addWidget(widget, index // 2, index % 2)
        self.body.addWidget(controls)

        mode = QGroupBox("裁剪模式")
        mode_layout = QHBoxLayout(mode)
        extract = QRadioButton("提取选中片段")
        delete = QRadioButton("删除选中片段")
        extract.setChecked(True)
        self.crop_mode_group = QButtonGroup(self)
        self.crop_mode_group.addButton(extract, 0)
        self.crop_mode_group.addButton(delete, 1)
        mode_layout.addWidget(extract)
        mode_layout.addWidget(delete)
        mode_layout.addStretch()
        self.body.addWidget(mode)

    def _build_speed_pitch(self):
        self.timeline = self._new_timeline(height=250, color="#35A99C")
        self.body.addWidget(self.timeline)
        self.body.addLayout(self._zoom_row(self.timeline))
        presets = QGroupBox("快速效果")
        preset_layout = QHBoxLayout(presets)
        for title, speed, pitch in (
            ("自定义", 1.0, 0),
            ("慢放", 0.75, 0),
            ("低沉", 1.0, -4),
            ("加速", 1.35, 0),
            ("明亮", 1.0, 4),
        ):
            button = QPushButton(title)
            button.clicked.connect(
                lambda _checked=False, s=speed, p=pitch: self._set_speed_preset(s, p)
            )
            preset_layout.addWidget(button)
        self.body.addWidget(presets)
        controls = QGroupBox("变速与变调")
        controls_layout = QVBoxLayout(controls)
        self.fields["speed"] = ValueSlider("变速", 0.25, 4, 1, step=0.05, suffix=" ×")
        self.fields["semitones"] = ValueSlider("变调", -12, 12, 0, step=1, suffix=" 半音")
        controls_layout.addWidget(self.fields["speed"])
        controls_layout.addWidget(self.fields["semitones"])
        hint = QLabel("变调以半音为单位：0 不变，正数升调，负数降调。")
        hint.setObjectName("workspaceHint")
        controls_layout.addWidget(hint)
        self.body.addWidget(controls)

    def _build_denoise(self):
        comparison = QGroupBox("处理前 / 处理后对比")
        comparison_layout = QGridLayout(comparison)
        original_title = QLabel("原始音频")
        processed_title = QLabel("处理预览")
        original_title.setObjectName("comparisonTitle")
        processed_title.setObjectName("comparisonTitle")
        comparison_layout.addWidget(original_title, 0, 0)
        comparison_layout.addWidget(processed_title, 0, 1)
        self.timeline = self._new_timeline(height=155, color="#4A90D9")
        self.processed_timeline = self._new_timeline(height=155, interactive=False, color="#35A99C")
        comparison_layout.addWidget(self.timeline, 1, 0)
        comparison_layout.addWidget(self.processed_timeline, 1, 1)
        self.body.addWidget(comparison)
        modes = QGroupBox("降噪模式")
        modes_layout = QHBoxLayout(modes)
        self.denoise_mode_group = QButtonGroup(self)
        for index, (title, tip) in enumerate(
            (
                ("轻度", "保留更多细节"),
                ("标准", "适合稳定底噪"),
                ("强力", "适合明显持续噪声"),
            )
        ):
            radio = QRadioButton(title)
            radio.setToolTip(tip)
            radio.setChecked(index == 1)
            self.denoise_mode_group.addButton(radio, index)
            modes_layout.addWidget(radio)
        modes_layout.addStretch()
        self.body.addWidget(modes)
        controls = QGroupBox("处理参数")
        controls_layout = QVBoxLayout(controls)
        self.fields["strength"] = ValueSlider("降噪强度", 1, 60, 20, step=1)
        self.fields["output_gain"] = ValueSlider("输出增益", -12, 12, 0, step=0.5, suffix=" dB")
        controls_layout.addWidget(self.fields["strength"])
        controls_layout.addWidget(self.fields["output_gain"])
        self.body.addWidget(controls)

    def _build_equalizer(self):
        playback = QFrame()
        playback.setObjectName("playbackStrip")
        playback_layout = QHBoxLayout(playback)
        playback_layout.addWidget(QLabel("试听当前均衡设置"))
        playback_layout.addStretch()
        self.eq_time_label = QLabel("0:00 / 0:00")
        playback_layout.addWidget(self.eq_time_label)
        self.body.addWidget(playback)
        balance_group = QGroupBox("声道平衡")
        balance_layout = QVBoxLayout(balance_group)
        self.fields["balance"] = ValueSlider("左右平衡", -100, 100, 0, step=1, suffix="%")
        balance_layout.addWidget(self.fields["balance"])
        self.body.addWidget(balance_group)
        bands_group = QGroupBox("八段均衡器")
        bands_layout = QHBoxLayout(bands_group)
        self.eq_bands: list[EqualizerBand] = []
        for frequency in ("60", "150", "400", "1k", "2.4k", "6k", "12k", "16k"):
            band = EqualizerBand(frequency)
            self.eq_bands.append(band)
            bands_layout.addWidget(band, 1)
        self.body.addWidget(bands_group)
        preset_row = QHBoxLayout()
        for title, values in (
            ("重置", [0] * 8),
            ("人声清晰", [-2, -1, 0, 2, 3, 2, 1, 0]),
            ("低频增强", [5, 4, 2, 0, -1, -1, 0, 0]),
            ("明亮", [-1, 0, 1, 2, 3, 4, 4, 3]),
        ):
            button = QPushButton(title)
            button.clicked.connect(
                lambda _checked=False, preset=values: self._set_eq_preset(preset)
            )
            preset_row.addWidget(button)
        preset_row.addStretch()
        self.body.addLayout(preset_row)

    def _build_mix(self):
        self._build_multitrack("多轨混音", allow_channel_mode=True)

    def _build_concat(self):
        self._build_multitrack("顺序拼接时间线", allow_channel_mode=False)

    def _build_multitrack(self, title: str, *, allow_channel_mode: bool):
        toolbar = QHBoxLayout()
        add = QPushButton("+ 添加轨道")
        add.setObjectName("primaryAction")
        add.clicked.connect(self._browse_tracks)
        toolbar.addWidget(add)
        toolbar.addWidget(QLabel("可对每条轨道静音、独奏并调整音量"))
        toolbar.addStretch()
        self.channel_mode = QCheckBox("左右声道合成")
        self.channel_mode.setVisible(allow_channel_mode)
        toolbar.addWidget(self.channel_mode)
        self.body.addLayout(toolbar)
        lanes = QGroupBox(title)
        lanes_layout = QVBoxLayout(lanes)
        ruler = QLabel("00:00       00:10       00:20       00:30       00:40       00:50")
        ruler.setObjectName("trackRuler")
        lanes_layout.addWidget(ruler)
        self.track_editor = TrackEditor()
        lanes_layout.addWidget(self.track_editor)
        self.body.addWidget(lanes, 1)
        options = QGroupBox("工程设置")
        options_layout = QHBoxLayout(options)
        self.duration_mode = QComboBox()
        self.duration_mode.addItem("最长轨道", "longest")
        self.duration_mode.addItem("最短轨道", "shortest")
        options_layout.addWidget(QLabel("输出时长"))
        options_layout.addWidget(self.duration_mode)
        self.master_gain = ValueSlider("主输出", -24, 12, 0, step=0.5, suffix=" dB")
        options_layout.addWidget(self.master_gain, 1)
        self.body.addWidget(options)

    def _build_volume(self):
        self.timeline = self._new_timeline(height=270, color="#5A8ED1")
        self.body.addWidget(self.timeline)
        self.body.addLayout(self._zoom_row(self.timeline))
        meter = QGroupBox("增益控制")
        meter_layout = QVBoxLayout(meter)
        self.gain_readout = QLabel("0.0 dB")
        self.gain_readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gain_readout.setObjectName("largeReadout")
        meter_layout.addWidget(self.gain_readout)
        self.fields["gain_db"] = ValueSlider("增益", -60, 30, 0, step=0.5, suffix=" dB")
        self.fields["gain_db"].valueChanged.connect(
            lambda value: self.gain_readout.setText(f"{value:+.1f} dB")
        )
        meter_layout.addWidget(self.fields["gain_db"])
        self.prevent_clipping = QCheckBox("自动限制峰值，避免削波")
        self.prevent_clipping.setChecked(True)
        meter_layout.addWidget(self.prevent_clipping)
        self.body.addWidget(meter)

    def _build_normalize(self):
        overview = QGroupBox("响度目标")
        overview_layout = QHBoxLayout(overview)
        for title, value in (("播客 / 语音", -16), ("流媒体音乐", -14), ("广播", -23)):
            button = QPushButton(f"{title}\n{value} LUFS")
            button.setMinimumHeight(55)
            button.clicked.connect(
                lambda _checked=False, target=value: self.fields["target_lufs"].setValue(target)
            )
            overview_layout.addWidget(button)
        self.body.addWidget(overview)
        meters = QHBoxLayout()
        for title in ("当前响度", "目标响度", "真峰值上限"):
            card = QFrame()
            card.setObjectName("meterCard")
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(QLabel(title))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(60 if title == "当前响度" else 72)
            bar.setTextVisible(False)
            card_layout.addWidget(bar)
            meters.addWidget(card)
        self.body.addLayout(meters)
        controls = QGroupBox("标准化参数")
        controls_layout = QVBoxLayout(controls)
        self.fields["target_lufs"] = ValueSlider("目标响度", -30, -5, -14, step=0.5, suffix=" LUFS")
        self.fields["true_peak"] = ValueSlider("真峰值", -5, -0.1, -1, step=0.1, suffix=" dBTP")
        controls_layout.addWidget(self.fields["target_lufs"])
        controls_layout.addWidget(self.fields["true_peak"])
        self.body.addWidget(controls)

    def _build_split(self):
        self.timeline = self._new_timeline(height=250, color="#7A78C9")
        self.body.addWidget(self.timeline)
        self.body.addLayout(self._zoom_row(self.timeline))
        settings = QGroupBox("分段规则")
        settings_layout = QVBoxLayout(settings)
        self.fields["segment_seconds"] = ValueSlider("每段时长", 1, 3600, 30, step=1, suffix=" 秒")
        self.fields["segment_seconds"].valueChanged.connect(self._update_split_summary)
        settings_layout.addWidget(self.fields["segment_seconds"])
        self.split_summary = QLabel("选择素材后显示预计片段数量")
        self.split_summary.setObjectName("selectionReadout")
        settings_layout.addWidget(self.split_summary)
        self.body.addWidget(settings)

    def _build_extract(self):
        card = QGroupBox("媒体音轨")
        card_layout = QGridLayout(card)
        self.extract_source = QLabel("尚未选择视频或媒体文件")
        self.extract_source.setObjectName("sourceCard")
        self.extract_source.setWordWrap(True)
        card_layout.addWidget(self.extract_source, 0, 0, 1, 3)
        card_layout.addWidget(QLabel("音轨"), 1, 0)
        self.audio_stream = QComboBox()
        self.audio_stream.addItem("主音轨（轨道 1）", 0)
        card_layout.addWidget(self.audio_stream, 1, 1, 1, 2)
        card_layout.addWidget(QLabel("输出格式"), 2, 0)
        self.extract_format = QComboBox()
        for label, suffix in (("MP3", ".mp3"), ("WAV", ".wav"), ("FLAC", ".flac")):
            self.extract_format.addItem(label, suffix)
        self.extract_format.currentIndexChanged.connect(self._extract_format_changed)
        card_layout.addWidget(self.extract_format, 2, 1)
        self.extract_quality = QComboBox()
        self.extract_quality.addItems(["高质量", "标准", "节省空间"])
        card_layout.addWidget(self.extract_quality, 2, 2)
        self.body.addWidget(card)
        hint = QLabel("只提取音频轨道，不改变原视频。输出会作为新文件保存。")
        hint.setObjectName("workspaceHint")
        self.body.addWidget(hint)

    def _build_tags(self):
        editor = QGroupBox("音乐信息")
        form = QGridLayout(editor)
        cover = QLabel("封面\n预览")
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setObjectName("coverPlaceholder")
        cover.setFixedSize(150, 150)
        form.addWidget(cover, 0, 0, 5, 1)
        for row, (key, label) in enumerate(
            (
                ("title", "标题"),
                ("artist", "歌手"),
                ("album", "专辑"),
                ("year", "年份"),
                ("track", "轨道号"),
            )
        ):
            edit = QLineEdit()
            self.fields[key] = edit
            form.addWidget(QLabel(label), row, 1)
            form.addWidget(edit, row, 2)
        self.body.addWidget(editor)
        note = QLabel("标签写入输出副本，不会重新编码音频，也不会覆盖原文件。")
        note.setObjectName("workspaceHint")
        self.body.addWidget(note)

    def _build_generic(self):
        form = QGroupBox("处理参数")
        form_layout = QFormLayout(form)
        for field in self.spec.fields:
            widget = self._field_widget(field)
            self.fields[field.key] = widget
            form_layout.addRow(field.label, widget)
        self.body.addWidget(form)

    def _build_output(self):
        self.body.addStretch()
        output = QFrame()
        output.setObjectName("outputBar")
        layout = QHBoxLayout(output)
        layout.addWidget(QLabel("输出"))
        layout.addWidget(self.output_edit, 1)
        browse = QPushButton("另存为")
        browse.clicked.connect(self._browse_output)
        layout.addWidget(browse)
        self.run_button = QPushButton(f"生成 {self.spec.title}")
        self.run_button.setObjectName("primaryAction")
        self.run_button.setMinimumHeight(38)
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self))
        layout.addWidget(self.run_button)
        self.body.addWidget(output)
        result_row = QHBoxLayout()
        self.result_label = QLabel("尚未生成结果")
        self.result_label.setObjectName("resultStatus")
        self.result_label.setWordWrap(True)
        result_row.addWidget(self.result_label, 1)
        self.result_play_button = QPushButton("试听结果")
        self.result_play_button.setVisible(False)
        self.result_play_button.clicked.connect(self.result_play_requested)
        result_row.addWidget(self.result_play_button)
        self.result_open_button = QPushButton("打开位置")
        self.result_open_button.setVisible(False)
        self.result_open_button.clicked.connect(self.result_open_requested)
        result_row.addWidget(self.result_open_button)
        self.body.addLayout(result_row)

    def set_primary_input(self, path: str):
        self._path = path
        self.input_edit.setText(path)
        self.source_label.setText(Path(path).name if path else "尚未选择素材")
        if self.track_editor is not None and path and not self.track_editor.paths():
            self.track_editor.add_path(path, emit=False)
        if path:
            self._set_default_output(path)
        if hasattr(self, "extract_source"):
            self.extract_source.setText(f"{Path(path).name}\n{Path(path).parent}")
        if self.spec.operation == "tags" and path:
            try:
                tags = read_tags(path)
            except Exception:
                tags = {}
            for key, widget in self.fields.items():
                if isinstance(widget, QLineEdit):
                    widget.setText(str(tags.get(key, "")))

    def set_audio(self, peaks: list[tuple[float, float]], duration: float):
        self._duration = max(0.0, duration)
        self._building_selection = True
        try:
            for timeline in self.timelines:
                timeline.set_audio(peaks, duration)
        finally:
            self._building_selection = False
        if hasattr(self, "selection_start"):
            self.selection_start.setMaximum(duration)
            self.selection_end.setMaximum(duration)
        if hasattr(self, "position_label"):
            self.position_label.setText(f"位置  0:00.000 / {self._format_time(duration)}")
        if hasattr(self, "eq_time_label"):
            self.eq_time_label.setText(f"0:00 / {self._format_time(duration)}")
        self._update_split_summary()

    def set_loading(self, duration: float):
        self._duration = max(0.0, duration)
        self._building_selection = True
        try:
            for timeline in self.timelines:
                timeline.set_audio([], duration)
                timeline.set_loading()
        finally:
            self._building_selection = False

    def set_processed_audio(self, peaks: list[tuple[float, float]], duration: float):
        if hasattr(self, "processed_timeline"):
            self.processed_timeline.set_audio(peaks, duration)

    def set_playhead(self, seconds: float):
        for timeline in self.timelines:
            timeline.set_playhead_seconds(seconds)
        if hasattr(self, "position_label"):
            self.position_label.setText(
                f"位置  {self._format_time(seconds)} / {self._format_time(self._duration)}"
            )
        if hasattr(self, "eq_time_label"):
            self.eq_time_label.setText(
                f"{self._format_time(seconds)} / {self._format_time(self._duration)}"
            )

    def set_playing(self, playing: bool):
        self.play_button.setText("暂停" if playing else "播放")

    def set_result_playing(self, playing: bool):
        self.result_play_button.setText("暂停结果" if playing else "试听结果")

    def set_selection(self, start: float, end: float, duration: float):
        self._selection = (max(0.0, start), max(0.0, end))
        self._duration = max(0.0, duration)
        self._building_selection = True
        for timeline in self.timelines:
            if timeline.interaction_enabled:
                timeline.set_selection_seconds(start, end, emit=False)
        if hasattr(self, "selection_start"):
            self.selection_start.setMaximum(duration)
            self.selection_end.setMaximum(duration)
            self.selection_start.setValue(start)
            self.selection_end.setValue(end)
        self._building_selection = False
        if hasattr(self, "selection_label"):
            self.selection_label.setText(f"已选  {self._format_time(max(0.0, end - start))}")

    def has_selection(self) -> bool:
        return self._selection[1] - self._selection[0] > 0.001

    def inputs(self) -> list[str]:
        if self.track_editor is not None:
            return self.track_editor.paths()
        return [self._path] if self._path else []

    def params(self) -> dict:
        result: dict = {}
        for key, widget in self.fields.items():
            if isinstance(widget, ValueSlider):
                result[key] = widget.value()
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                result[key] = widget.value()
            elif isinstance(widget, QComboBox):
                result[key] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                result[key] = widget.text().strip()
        if self.spec.key == "trim":
            result["crop_mode"] = "delete" if self.crop_mode_group.checkedId() == 1 else "extract"
        if self.spec.key == "denoise":
            result["denoise_mode"] = self.denoise_mode_group.checkedId()
        if self.spec.key == "equalizer":
            result["bands"] = [band.value() for band in self.eq_bands]
        if self.track_editor is not None:
            result["volumes"] = self.track_editor.volumes()
            result["duration_mode"] = self.duration_mode.currentData()
            result["master_gain"] = self.master_gain.value()
            result["mix_mode"] = (
                "stereo"
                if self.channel_mode.isVisible() and self.channel_mode.isChecked()
                else "mix"
            )
        if self.spec.key == "volume":
            result["prevent_clipping"] = self.prevent_clipping.isChecked()
        if self.spec.selection_aware and self.has_selection():
            result["selection_start"] = self._selection[0]
            result["selection_end"] = self._selection[1]
        return result

    def operation(self) -> str:
        return self.spec.operation

    def set_result(self, path: str, message: str):
        self._result_path = path
        self.result_label.setText(f"{message}  {Path(path).name}")
        self.result_play_button.setVisible(True)
        self.result_open_button.setVisible(True)

    def _timeline_selection_changed(self, start: float, end: float):
        if self._building_selection:
            return
        self._selection = (start, end)
        self.selection_requested.emit(start, end)

    def _selection_fields_changed(self):
        if self._building_selection:
            return
        self.selection_requested.emit(self.selection_start.value(), self.selection_end.value())

    def _set_speed_preset(self, speed: float, pitch: float):
        self.fields["speed"].setValue(speed)
        self.fields["semitones"].setValue(pitch)

    def _set_eq_preset(self, values: list[float]):
        for band, value in zip(self.eq_bands, values, strict=True):
            band.setValue(value)

    def _update_split_summary(self, *_args):
        if not hasattr(self, "split_summary"):
            return
        seconds = max(1.0, self.fields["segment_seconds"].value())
        selected = self._selection[1] - self._selection[0]
        duration = selected if selected > 0.001 else self._duration
        count = max(0, int((duration + seconds - 0.001) // seconds))
        self.split_summary.setText(
            f"当前范围 {self._format_time(duration)}，预计生成 {count} 个连续片段"
        )

    def _browse_tracks(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加音频轨道",
            "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;所有文件 (*)",
        )
        for path in paths:
            self.track_editor.add_path(path)
        if paths and not self.output_edit.text():
            self._set_default_output(paths[0])

    def _extract_format_changed(self):
        if not self._path:
            return
        suffix = self.extract_format.currentData()
        path = Path(self.output_edit.text())
        self.output_edit.setText(str(path.with_suffix(suffix)))

    def _set_default_output(self, input_path: str):
        path = Path(input_path)
        folder = path.parent / "Echovault编辑输出"
        suffix = path.suffix if self.spec.operation == "tags" else self.spec.output_suffix
        if self.spec.key == "extract" and hasattr(self, "extract_format"):
            suffix = self.extract_format.currentData()
        self.output_edit.setText(str(folder / f"{path.stem}_{self.spec.key}{suffix}"))

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择输出文件",
            self.output_edit.text().strip(),
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg *.opus);;所有文件 (*)",
        )
        if path:
            self.output_edit.setText(path)

    @staticmethod
    def _field_widget(field):
        if field.kind == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(2)
            widget.setRange(field.minimum, field.maximum)
            widget.setValue(float(field.default))
            widget.setSuffix(field.suffix)
            return widget
        if field.kind == "int":
            widget = QSpinBox()
            widget.setRange(int(field.minimum), int(field.maximum))
            widget.setValue(int(field.default))
            widget.setSuffix(field.suffix)
            return widget
        if field.kind == "choice":
            widget = QComboBox()
            for label, value in field.choices:
                widget.addItem(label, value)
            return widget
        return QLineEdit(str(field.default))

    @staticmethod
    def _time_spin():
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(0, 86400)
        spin.setSuffix(" 秒")
        spin.setMinimumWidth(130)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def _format_time(seconds: float) -> str:
        milliseconds = int(round(max(0.0, seconds) * 1000))
        minutes, remainder = divmod(milliseconds, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{minutes}:{secs:02d}.{millis:03d}"

    @staticmethod
    def _style() -> str:
        return """
        QFrame#toolWorkspaceSurface {
            background:#FFFFFF; border:1px solid #DDE3EA; border-radius:11px;
        }
        QLabel#workspaceTitle { color:#14213D; font-size:20px; font-weight:700; }
        QLabel#workspaceDescription, QLabel#workspaceHint { color:#667085; }
        QLabel#sourceChip {
            background:#F3F6FA; color:#475569; border-radius:7px; padding:8px 10px;
        }
        QPushButton#workspacePlay { min-width:72px; min-height:34px; }
        QLabel#positionReadout { color:#E26B72; font-size:15px; font-weight:700; }
        QLabel#selectionReadout { color:#1F6FBB; font-size:14px; font-weight:700; }
        QLabel#comparisonTitle { font-size:14px; font-weight:700; color:#334155; }
        QLabel#eqValue { color:#E26B72; font-weight:700; }
        QLabel#largeReadout { color:#1F6FBB; font-size:27px; font-weight:700; padding:8px; }
        QLabel#trackRuler { background:#F0F8F6; color:#2E9E8B; padding:8px; font-family:Consolas; }
        QLabel#emptyTrackHint { color:#94A3B8; background:#F8FAFC; border:1px dashed #CBD5E1; }
        QLabel#sourceCard { background:#F7F9FC; border-radius:7px; padding:14px; color:#334155; }
        QLabel#coverPlaceholder {
            background:#EDF2F7; color:#64748B;
            border:1px dashed #B8C4D2; border-radius:8px;
        }
        QLabel#resultStatus { color:#667085; font-size:11px; }
        QFrame#outputBar, QFrame#playbackStrip, QFrame#meterCard, QFrame#trackRow {
            background:#F7F9FC; border:1px solid #E1E7EF; border-radius:8px;
        }
        QFrame#trackRow:hover { border-color:#9FC3E7; background:#F2F7FD; }
        QPushButton#trackToggle { border-radius:14px; padding:0; background:#E5E7EB; }
        QPushButton#trackToggle:checked { background:#2F7DD1; color:white; }
        QPushButton#roundStepButton { border-radius:14px; padding:0; font-size:17px; }
        QPushButton#quietDanger { color:#B64B4B; }
        """
