"""Selection-driven audio editing workspace backed by FFmpeg and Mutagen."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.audio_editor import AudioEditResult, process_audio
from core.audio_utils import get_audio_info
from core.audio_waveform import extract_waveform_peaks
from core.metadata import read_tags
from ui.audio_timeline import AudioTimeline


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    default: object
    minimum: float = -9999
    maximum: float = 9999
    suffix: str = ""
    choices: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class ToolSpec:
    key: str
    title: str
    description: str
    operation: str
    fields: tuple[FieldSpec, ...] = ()
    multi_input: bool = False
    output_suffix: str = ".wav"
    selection_aware: bool = True


TOOLS = (
    ToolSpec(
        "trim",
        "裁剪与淡化",
        "在波形中拖出要保留的范围，可同时制作自然的淡入和淡出。",
        "edit",
        (
            FieldSpec("fade_in", "淡入时长", "float", 0.0, 0, 60, " 秒"),
            FieldSpec("fade_out", "淡出时长", "float", 0.0, 0, 60, " 秒"),
        ),
    ),
    ToolSpec(
        "split",
        "分段导出",
        "将整段或当前选区按固定时长连续导出为多个文件。",
        "split",
        (FieldSpec("segment_seconds", "每段时长", "float", 30.0, 1, 3600, " 秒"),),
    ),
    ToolSpec(
        "volume",
        "增益",
        "以分贝精确调整整段或当前选区的响度。",
        "volume",
        (FieldSpec("gain_db", "增益", "float", 0.0, -60, 30, " dB"),),
    ),
    ToolSpec(
        "denoise",
        "底噪抑制",
        "使用 FFT 降噪降低稳定、持续的背景底噪。",
        "denoise",
        (FieldSpec("noise_floor", "噪声底限", "float", -25.0, -80, -20, " dB"),),
    ),
    ToolSpec(
        "normalize",
        "响度标准化",
        "按 LUFS 与真峰值标准统一音频的主观响度。",
        "normalize",
        (
            FieldSpec("target_lufs", "目标响度", "float", -14.0, -30, -5, " LUFS"),
            FieldSpec("true_peak", "最大真峰值", "float", -1.0, -5, -0.1, " dBTP"),
        ),
    ),
    ToolSpec(
        "equalizer",
        "三段均衡器",
        "分别调整低频、中频与高频，塑造声音的整体色彩。",
        "equalizer",
        (
            FieldSpec("bass", "低频", "float", 0.0, -20, 20, " dB"),
            FieldSpec("middle", "中频", "float", 0.0, -20, 20, " dB"),
            FieldSpec("treble", "高频", "float", 0.0, -20, 20, " dB"),
        ),
    ),
    ToolSpec(
        "speed_pitch",
        "变速与变调",
        "独立调整播放速度和音高半音。",
        "speed_pitch",
        (
            FieldSpec("speed", "速度", "float", 1.0, 0.25, 4.0, " ×"),
            FieldSpec("semitones", "音高", "float", 0.0, -12, 12, " 半音"),
        ),
    ),
    ToolSpec(
        "concat",
        "顺序拼接",
        "按列表顺序把两个或更多音频首尾拼接。",
        "concat",
        multi_input=True,
        selection_aware=False,
    ),
    ToolSpec(
        "mix",
        "多轨混合",
        "让多个音频从同一时间点播放并混合，可分别设置音量倍率。",
        "mix",
        (FieldSpec("volumes", "音量倍率", "text", "1,1"),),
        multi_input=True,
        selection_aware=False,
    ),
    ToolSpec(
        "extract",
        "提取音轨",
        "从当前视频或媒体文件提取独立音轨。",
        "extract",
        output_suffix=".mp3",
        selection_aware=False,
    ),
    ToolSpec(
        "tags",
        "音频标签",
        "为输出副本编辑标题、歌手、专辑、年份和轨道号。",
        "tags",
        (
            FieldSpec("title", "标题", "text", ""),
            FieldSpec("artist", "歌手", "text", ""),
            FieldSpec("album", "专辑", "text", ""),
            FieldSpec("year", "年份", "text", ""),
            FieldSpec("track", "轨道号", "text", ""),
        ),
        output_suffix=".mp3",
        selection_aware=False,
    ),
)


TOOL_GROUPS = (
    ("编辑", ("trim", "split", "volume")),
    ("修复与音色", ("denoise", "normalize", "equalizer", "speed_pitch")),
    ("合成与输出", ("concat", "mix", "extract", "tags")),
)


class AudioEditorWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, inputs, output_path, params, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.inputs = list(inputs)
        self.output_path = output_path
        self.params = dict(params)

    def run(self):
        try:
            self.completed.emit(
                process_audio(self.operation, self.inputs, self.output_path, self.params)
            )
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class WaveformLoadWorker(QThread):
    completed = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        try:
            self.completed.emit(self.file_path, extract_waveform_peaks(self.file_path))
        except (OSError, RuntimeError) as exc:
            self.failed.emit(self.file_path, str(exc))


class AudioToolPage(QWidget):
    run_requested = pyqtSignal(object)

    def __init__(self, spec: ToolSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.fields: dict[str, QWidget] = {}
        self._selection = (0.0, 0.0)
        self._duration = 0.0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(12)

        heading = QLabel(self.spec.title)
        heading.setObjectName("audioToolHeading")
        layout.addWidget(heading)
        note = QLabel(self.spec.description)
        note.setWordWrap(True)
        note.setObjectName("audioToolDescription")
        layout.addWidget(note)

        scope_group = QGroupBox("处理对象")
        scope_layout = QVBoxLayout(scope_group)
        self.input_summary = QLabel("尚未选择素材")
        self.input_summary.setWordWrap(True)
        self.input_summary.setObjectName("audioScopeSummary")
        scope_layout.addWidget(self.input_summary)
        self.scope_summary = QLabel("处理范围：整段")
        self.scope_summary.setWordWrap(True)
        self.scope_summary.setObjectName("audioScopeBadge")
        scope_layout.addWidget(self.scope_summary)
        layout.addWidget(scope_group)

        if self.spec.multi_input:
            inputs_group = QGroupBox("轨道列表")
            inputs_layout = QVBoxLayout(inputs_group)
            self.input_edit = QPlainTextEdit()
            self.input_edit.setPlaceholderText("每行一个音频文件，顺序从上到下")
            self.input_edit.setMinimumHeight(130)
            inputs_layout.addWidget(self.input_edit)
            add_inputs = QPushButton("添加音频文件")
            add_inputs.clicked.connect(self._browse_multi_inputs)
            inputs_layout.addWidget(add_inputs)
            layout.addWidget(inputs_group)
        else:
            self.input_edit = QLineEdit()
            self.input_edit.hide()

        if self.spec.fields:
            parameter_group = QGroupBox("参数")
            parameter_form = QFormLayout(parameter_group)
            parameter_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for field in self.spec.fields:
                widget = self._field_widget(field)
                self.fields[field.key] = widget
                parameter_form.addRow(field.label + ":", widget)
            layout.addWidget(parameter_group)

        output_group = QGroupBox("输出")
        output_layout = QVBoxLayout(output_group)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("选择素材后自动生成输出路径")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_browse = QPushButton("另存为")
        output_browse.clicked.connect(self._browse_output)
        output_row.addWidget(output_browse)
        output_layout.addLayout(output_row)
        output_note = QLabel("始终生成新文件，不覆盖原素材。")
        output_note.setObjectName("audioOutputNote")
        output_layout.addWidget(output_note)
        layout.addWidget(output_group)

        self.run_button = QPushButton(f"生成：{self.spec.title}")
        self.run_button.setObjectName("primaryAction")
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self))
        layout.addWidget(self.run_button)
        layout.addStretch()

    def _field_widget(self, field: FieldSpec):
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
            widget.setCurrentIndex(max(0, widget.findData(field.default)))
            return widget
        return QLineEdit(str(field.default))

    def set_primary_input(self, path: str):
        if self.spec.multi_input:
            existing = self.input_edit.toPlainText().splitlines()
            if path and path not in existing:
                self.input_edit.setPlainText(path)
        else:
            self.input_edit.setText(path)
        self.input_summary.setText(Path(path).name if path else "尚未选择素材")
        if path:
            self._set_default_output(path)
            if self.spec.operation == "tags":
                try:
                    tags = read_tags(path)
                except Exception:
                    tags = {}
                for key, widget in self.fields.items():
                    if isinstance(widget, QLineEdit):
                        widget.setText(str(tags.get(key, "")))

    def set_selection(self, start: float, end: float, duration: float):
        self._selection = (max(0.0, start), max(0.0, end))
        self._duration = max(0.0, duration)
        if not self.spec.selection_aware:
            self.scope_summary.setText("处理范围：不使用时间选区")
            return
        if end - start > 0.001:
            self.scope_summary.setText(
                f"处理范围：当前选区 {self._format_time(start)} – {self._format_time(end)}\n"
                "效果结果只包含当前选区。"
            )
        else:
            self.scope_summary.setText("处理范围：整段素材")

    @staticmethod
    def _format_time(seconds: float) -> str:
        minutes, secs = divmod(max(0.0, seconds), 60)
        return f"{int(minutes)}:{secs:06.3f}"

    def has_selection(self) -> bool:
        return self._selection[1] - self._selection[0] > 0.001

    def _set_default_output(self, input_path: str):
        path = Path(input_path)
        folder = path.parent / "Echovault编辑输出"
        suffix = path.suffix if self.spec.operation == "tags" else self.spec.output_suffix
        self.output_edit.setText(str(folder / f"{path.stem}_{self.spec.key}{suffix}"))

    def inputs(self) -> list[str]:
        if self.spec.multi_input:
            return [
                value.strip()
                for value in self.input_edit.toPlainText().splitlines()
                if value.strip()
            ]
        value = self.input_edit.text().strip()
        return [value] if value else []

    def params(self) -> dict:
        result = {}
        for key, widget in self.fields.items():
            if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                result[key] = widget.value()
            elif isinstance(widget, QComboBox):
                result[key] = widget.currentData()
            else:
                result[key] = widget.text().strip()
        if self.spec.operation == "mix":
            raw = str(result.get("volumes", ""))
            result["volumes"] = [
                float(value.strip()) for value in raw.split(",") if value.strip()
            ]
        if self.spec.selection_aware and self.has_selection():
            result["selection_start"] = self._selection[0]
            result["selection_end"] = self._selection[1]
        return result

    def operation(self) -> str:
        return self.spec.operation

    def _browse_multi_inputs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加音频轨道",
            "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;所有文件 (*)",
        )
        if not paths:
            return
        existing = [line for line in self.input_edit.toPlainText().splitlines() if line]
        merged = existing + [path for path in paths if path not in existing]
        self.input_edit.setPlainText("\n".join(merged))
        if merged:
            self._set_default_output(merged[0])

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择输出文件",
            self.output_edit.text().strip(),
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg *.opus);;所有文件 (*)",
        )
        if path:
            self.output_edit.setText(path)


class AudioEditorPanel(QWidget):
    """Professional single-waveform editor with task-specific effect controls."""

    output_created = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._song: dict = {}
        self._songs: list[dict] = []
        self._duration = 0.0
        self._worker: AudioEditorWorker | None = None
        self._waveform_worker: WaveformLoadWorker | None = None
        self._last_output = ""
        self._playing_path = ""
        self._updating_selection_fields = False
        self._updating_scrollbar = False
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        editor_splitter.addWidget(self._build_tool_navigation())
        editor_splitter.addWidget(self._build_editor_workspace())

        self.stack = QStackedWidget()
        self.tool_pages: dict[str, AudioToolPage] = {}
        for spec in TOOLS:
            page = AudioToolPage(spec)
            page.run_requested.connect(self._run_tool)
            self.tool_pages[spec.key] = page
            self.stack.addWidget(page)
        parameter_frame = QFrame()
        parameter_frame.setObjectName("audioParameterPanel")
        parameter_frame.setMinimumWidth(310)
        parameter_frame.setMaximumWidth(420)
        parameter_layout = QVBoxLayout(parameter_frame)
        parameter_layout.setContentsMargins(0, 0, 0, 0)
        parameter_scroll = QScrollArea()
        parameter_scroll.setWidgetResizable(True)
        parameter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        parameter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        parameter_scroll.setWidget(self.stack)
        parameter_layout.addWidget(parameter_scroll)
        self.parameter_scroll = parameter_scroll
        editor_splitter.addWidget(parameter_frame)
        editor_splitter.setStretchFactor(0, 0)
        editor_splitter.setStretchFactor(1, 1)
        editor_splitter.setStretchFactor(2, 0)
        editor_splitter.setSizes([185, 660, 355])
        layout.addWidget(editor_splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("在波形中拖动可创建选区；所有处理都会生成新文件。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("audioEditorStatus")
        layout.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#audioToolRail, QFrame#audioEditorSurface,
            QFrame#audioParameterPanel {
                background:#FFFFFF;
                border:1px solid #DDE3EA;
                border-radius:11px;
            }
            QPushButton#audioToolButton {
                background:transparent;
                border:1px solid transparent;
                border-radius:7px;
                color:#334155;
                min-height:30px;
                padding:4px 10px;
                text-align:left;
            }
            QPushButton#audioToolButton:hover { background:#EEF4FB; }
            QPushButton#audioToolButton:checked {
                background:#E7F1FC;
                border-color:#B7D1EC;
                color:#1F6FBB;
                font-weight:700;
            }
            QLabel#audioToolHeading { font-size:18px;font-weight:700;color:#14213D; }
            QLabel#audioToolDescription { color:#667085;padding-bottom:4px; }
            QLabel#audioScopeSummary {
                color:#334155;background:#F7F9FC;padding:9px;border-radius:6px;
            }
            QLabel#audioScopeBadge {
                color:#1F5F9C;background:#EDF5FD;padding:8px;border-radius:6px;
            }
            QLabel#audioOutputNote, QLabel#audioEditorStatus {
                color:#667085;font-size:11px;
            }
            """
        )
        self._open_tool("trim")

    def _build_tool_navigation(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(170)
        scroll.setMaximumWidth(210)
        rail = QFrame()
        rail.setObjectName("audioToolRail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(8, 10, 8, 10)
        rail_layout.setSpacing(3)
        title = QLabel("处理工具")
        title.setStyleSheet("font-size:15px;font-weight:700;color:#14213D;padding:2px 6px")
        rail_layout.addWidget(title)
        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.setExclusive(True)
        self.tool_buttons = {}
        by_key = {spec.key: spec for spec in TOOLS}
        for group_title, keys in TOOL_GROUPS:
            group = QLabel(group_title)
            group.setStyleSheet(
                "color:#64748B;font-size:11px;font-weight:700;padding:9px 7px 3px"
            )
            rail_layout.addWidget(group)
            for key in keys:
                spec = by_key[key]
                button = QPushButton(spec.title)
                button.setObjectName("audioToolButton")
                button.setCheckable(True)
                button.setToolTip(spec.description)
                button.clicked.connect(
                    lambda _checked=False, target=key: self._open_tool(target)
                )
                self.tool_button_group.addButton(button)
                self.tool_buttons[key] = button
                rail_layout.addWidget(button)
        rail_layout.addStretch()
        scroll.setWidget(rail)
        self.tool_navigation_scroll = scroll
        return scroll

    def _build_editor_workspace(self):
        frame = QFrame()
        frame.setObjectName("audioEditorSurface")
        frame.setMinimumWidth(520)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel("波形编辑器")
        heading.setStyleSheet("font-size:15px;font-weight:700;color:#14213D")
        header.addWidget(heading)
        header.addStretch()
        self.current_label = QLabel("未选择素材")
        self.current_label.setStyleSheet("color:#667085")
        header.addWidget(self.current_label)
        layout.addLayout(header)

        self.material_info = QLabel("请先从素材工作区选择音乐或视频")
        self.material_info.setWordWrap(True)
        self.material_info.setObjectName("audioMaterialInfo")
        self.material_info.setStyleSheet(
            "background:#F7F9FC;color:#475569;padding:9px;border-radius:6px"
        )
        layout.addWidget(self.material_info)

        toolbar = QHBoxLayout()
        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("primaryAction")
        self.play_button.setMaximumWidth(88)
        self.play_button.clicked.connect(self._toggle_playback)
        toolbar.addWidget(self.play_button)
        select_all = QPushButton("全选")
        select_all.setMaximumWidth(74)
        select_all.clicked.connect(self.timeline_select_all)
        toolbar.addWidget(select_all)
        clear = QPushButton("清除选区")
        clear.setMaximumWidth(96)
        clear.clicked.connect(self.timeline_clear_selection)
        toolbar.addWidget(clear)
        toolbar.addStretch()
        zoom_in = QPushButton("放大")
        zoom_in.setMaximumWidth(72)
        zoom_in.clicked.connect(lambda: self.timeline.zoom(0.65))
        toolbar.addWidget(zoom_in)
        zoom_out = QPushButton("缩小")
        zoom_out.setMaximumWidth(72)
        zoom_out.clicked.connect(lambda: self.timeline.zoom(1.5))
        toolbar.addWidget(zoom_out)
        zoom_selection = QPushButton("适应选区")
        zoom_selection.setMaximumWidth(96)
        zoom_selection.clicked.connect(lambda: self.timeline.zoom_to_selection())
        toolbar.addWidget(zoom_selection)
        show_all = QPushButton("显示全部")
        show_all.setMaximumWidth(88)
        show_all.clicked.connect(lambda: self.timeline.show_all())
        toolbar.addWidget(show_all)
        layout.addLayout(toolbar)

        self.timeline = AudioTimeline()
        self.timeline.seek_requested.connect(self._seek_preview_seconds)
        self.timeline.selection_changed.connect(self._selection_changed)
        self.timeline.view_changed.connect(self._timeline_view_changed)
        layout.addWidget(self.timeline, 1)

        self.timeline_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.timeline_scroll.setRange(0, 10000)
        self.timeline_scroll.setPageStep(10000)
        self.timeline_scroll.valueChanged.connect(self._timeline_scrolled)
        layout.addWidget(self.timeline_scroll)

        selection = QGroupBox("选区 / 游标")
        selection_layout = QHBoxLayout(selection)
        self.selection_start = self._time_spin()
        self.selection_end = self._time_spin()
        self.selection_duration = self._time_spin()
        self.selection_duration.setReadOnly(True)
        self.selection_start.valueChanged.connect(self._selection_fields_changed)
        self.selection_end.valueChanged.connect(self._selection_fields_changed)
        selection_layout.addWidget(QLabel("起点"))
        selection_layout.addWidget(self.selection_start)
        selection_layout.addWidget(QLabel("终点"))
        selection_layout.addWidget(self.selection_end)
        selection_layout.addWidget(QLabel("时长"))
        selection_layout.addWidget(self.selection_duration)
        self.playhead_label = QLabel("游标 0:00.000")
        self.playhead_label.setStyleSheet("font-weight:700;color:#334155;padding-left:8px")
        selection_layout.addWidget(self.playhead_label)
        layout.addWidget(selection)

        self.result_frame = QFrame()
        self.result_frame.setObjectName("audioResultBar")
        result_layout = QHBoxLayout(self.result_frame)
        result_layout.setContentsMargins(9, 7, 9, 7)
        self.result_label = QLabel("尚未生成编辑结果")
        self.result_label.setWordWrap(True)
        result_layout.addWidget(self.result_label, 1)
        self.preview_result_button = QPushButton("试听结果")
        self.preview_result_button.clicked.connect(self._preview_last_result)
        self.preview_result_button.setVisible(False)
        result_layout.addWidget(self.preview_result_button)
        self.open_result_button = QPushButton("打开位置")
        self.open_result_button.clicked.connect(self._open_last_result_folder)
        self.open_result_button.setVisible(False)
        result_layout.addWidget(self.open_result_button)
        self.result_frame.setStyleSheet(
            "QFrame#audioResultBar{background:#F7F9FC;border:1px solid #E1E7EF;border-radius:7px}"
        )
        layout.addWidget(self.result_frame)

        self._player.positionChanged.connect(self._preview_position_changed)
        self._player.durationChanged.connect(self._preview_duration_changed)
        self._player.playbackStateChanged.connect(self._playback_state_changed)
        return frame

    @staticmethod
    def _time_spin():
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(0, 86400)
        spin.setSuffix(" 秒")
        spin.setKeyboardTracking(False)
        spin.setMinimumWidth(92)
        spin.setMaximumWidth(118)
        return spin

    def set_songs(self, songs: list[dict]):
        self._songs = [dict(song) for song in songs if song.get("path")]

    def show_song(self, song: dict):
        if not song or not song.get("path"):
            return
        self._song = dict(song)
        path = str(song["path"])
        self.current_label.setText(Path(path).name)
        try:
            info = get_audio_info(path)
            self._duration = float(info.get("duration") or 0.0)
            self.material_info.setText(
                f"{Path(path).name}\n{Path(path).parent}\n"
                f"{self._format_time(self._duration)}　"
                f"{info.get('sample_rate', 0)} Hz　{info.get('channels', 0)} 声道"
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._duration = 0.0
            self.material_info.setText(f"{Path(path).name}\n无法读取音频信息：{exc}")
        self.timeline.set_audio([], self._duration)
        self.timeline.set_loading()
        self._configure_selection_fields()
        for page in self.tool_pages.values():
            page.set_primary_input(path)
            page.set_selection(0.0, 0.0, self._duration)
        self._start_waveform_load(path)
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self._playing_path = path
        self.status_label.setText("正在分析波形；可先设置处理工具与输出参数。")

    def select_song(self, path: str):
        song = next((item for item in self._songs if item.get("path") == path), None)
        if song:
            self.show_song(song)

    def _start_waveform_load(self, path: str):
        worker = WaveformLoadWorker(path, self)
        worker.completed.connect(self._waveform_loaded)
        worker.failed.connect(self._waveform_failed)
        worker.finished.connect(worker.deleteLater)
        self._waveform_worker = worker
        worker.start()

    def _waveform_loaded(self, path: str, peaks: list[tuple[float, float]]):
        if path != str(self._song.get("path", "")):
            return
        self.timeline.set_audio(peaks, self._duration)
        self._configure_selection_fields()
        self.status_label.setText("拖动波形创建选区；滚轮或工具栏可缩放时间轴。")

    def _waveform_failed(self, path: str, message: str):
        if path == str(self._song.get("path", "")):
            self.status_label.setText(f"波形生成失败：{message}")

    def timeline_select_all(self):
        self.timeline.select_all()

    def timeline_clear_selection(self):
        self.timeline.clear_selection()

    def _configure_selection_fields(self):
        self._updating_selection_fields = True
        for spin in (self.selection_start, self.selection_end, self.selection_duration):
            spin.setMaximum(max(0.0, self._duration))
            spin.setValue(0.0)
        self._updating_selection_fields = False

    def _selection_changed(self, start: float, end: float):
        self._updating_selection_fields = True
        self.selection_start.setValue(start)
        self.selection_end.setValue(end)
        self.selection_duration.setValue(max(0.0, end - start))
        self._updating_selection_fields = False
        for page in self.tool_pages.values():
            page.set_selection(start, end, self._duration)
        if end - start > 0.001:
            self.status_label.setText(
                f"已选择 {self._format_time(start)} – {self._format_time(end)}，"
                f"共 {self._format_time(end - start)}。"
            )
        else:
            self.status_label.setText("未选择时间范围；支持选区的效果将处理整段素材。")

    def _selection_fields_changed(self):
        if self._updating_selection_fields:
            return
        self.timeline.set_selection_seconds(
            self.selection_start.value(), self.selection_end.value()
        )

    def _timeline_view_changed(self, start: float, end: float):
        self._updating_scrollbar = True
        span = max(0.01, end - start)
        self.timeline_scroll.setPageStep(max(1, int(span * 10000)))
        self.timeline_scroll.setValue(int(start * 10000))
        self.timeline_scroll.setEnabled(span < 0.999)
        self._updating_scrollbar = False

    def _timeline_scrolled(self, value: int):
        if self._updating_scrollbar:
            return
        span = self.timeline.view_end - self.timeline.view_start
        start = min(1.0 - span, value / 10000.0)
        self.timeline.set_view(start, start + span)

    def _open_tool(self, key: str):
        if key not in self.tool_pages:
            return
        self.tool_buttons[key].setChecked(True)
        page = self.tool_pages[key]
        if self._song.get("path"):
            page.set_primary_input(str(self._song["path"]))
            page.set_selection(
                self.timeline.selection_start,
                self.timeline.selection_end,
                self._duration,
            )
        self.stack.setCurrentWidget(page)

    def _run_tool(self, page: AudioToolPage):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "音频编辑", "当前已有音频任务正在处理。")
            return
        inputs = page.inputs()
        if not inputs:
            QMessageBox.information(self, "音频编辑", "请先选择素材。")
            return
        if page.spec.key == "trim" and not page.has_selection():
            QMessageBox.information(self, "裁剪与淡化", "请先在波形中拖动选择要保留的范围。")
            return
        output_path = page.output_edit.text().strip()
        if not output_path:
            QMessageBox.information(self, "音频编辑", "请先选择输出文件。")
            return
        try:
            params = page.params()
        except ValueError as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        operation = page.operation()
        page.run_button.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText(f"正在执行：{page.spec.title}…")
        self._worker = AudioEditorWorker(operation, inputs, output_path, params, self)
        self._worker.completed.connect(
            lambda result, target=page, source=inputs[0], name=operation: (
                self._on_process_completed(target, result, source, name)
            )
        )
        self._worker.failed.connect(
            lambda message, target=page: self._on_process_failed(target, message)
        )
        self._worker.start()

    def _on_process_completed(
        self,
        page: AudioToolPage,
        result: AudioEditResult,
        source_path: str,
        operation: str,
    ):
        page.run_button.setEnabled(True)
        self.progress.setVisible(False)
        self._worker = None
        for output in result.outputs:
            self.output_created.emit(source_path, output, operation)
        self._last_output = result.outputs[-1]
        self.result_label.setText(
            f"最近结果：{Path(self._last_output).name}\n{Path(self._last_output).parent}"
        )
        self.preview_result_button.setVisible(True)
        self.open_result_button.setVisible(True)
        self.status_label.setText(result.message)

    def _on_process_failed(self, page: AudioToolPage, message: str):
        page.run_button.setEnabled(True)
        self.progress.setVisible(False)
        self._worker = None
        self.status_label.setText(f"处理失败：{message}")
        QMessageBox.warning(self, "音频编辑失败", message)

    def _toggle_playback(self):
        source = str(self._song.get("path", ""))
        if not source:
            QMessageBox.information(self, "试听", "请先从素材工作区选择文件。")
            return
        if (
            self._playing_path == source
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.pause()
            return
        url = QUrl.fromLocalFile(str(Path(source).resolve()))
        if self._player.source() != url:
            self._player.setSource(url)
        self._playing_path = source
        if self.timeline.has_selection():
            current = self._player.position() / 1000.0
            if not self.timeline.selection_start <= current < self.timeline.selection_end:
                self._player.setPosition(int(self.timeline.selection_start * 1000))
        self._player.play()

    def _preview_last_result(self):
        if not self._last_output or not Path(self._last_output).is_file():
            return
        if (
            self._playing_path == self._last_output
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.pause()
            return
        self._playing_path = self._last_output
        self._player.setSource(QUrl.fromLocalFile(str(Path(self._last_output).resolve())))
        self._player.play()

    def _open_last_result_folder(self):
        if self._last_output and Path(self._last_output).exists():
            os.startfile(str(Path(self._last_output).parent))

    def _seek_preview_seconds(self, seconds: float):
        source = str(self._song.get("path", ""))
        if not source:
            return
        url = QUrl.fromLocalFile(str(Path(source).resolve()))
        if self._player.source() != url:
            self._player.setSource(url)
        self._playing_path = source
        self._player.setPosition(int(seconds * 1000))

    def _preview_position_changed(self, position: int):
        source = str(self._song.get("path", ""))
        seconds = position / 1000.0
        if self._playing_path == source:
            self.timeline.set_playhead_seconds(seconds)
            self.playhead_label.setText(f"游标 {self._format_time(seconds)}")
            if (
                self.timeline.has_selection()
                and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                and seconds >= self.timeline.selection_end
            ):
                self._player.pause()
                self._player.setPosition(int(self.timeline.selection_start * 1000))

    def _preview_duration_changed(self, _duration: int):
        return

    def _playback_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        source = str(self._song.get("path", ""))
        self.play_button.setText(
            "暂停" if playing and self._playing_path == source else "播放"
        )
        if self._last_output:
            self.preview_result_button.setText(
                "暂停结果" if playing and self._playing_path == self._last_output else "试听结果"
            )

    @staticmethod
    def _format_time(seconds: float) -> str:
        milliseconds = int(round(max(0.0, seconds) * 1000))
        minutes, remainder = divmod(milliseconds, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{minutes}:{secs:02d}.{millis:03d}"
