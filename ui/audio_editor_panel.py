"""Right-side audio editing workspace backed by FFmpeg and Mutagen."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import (
    QAudioFormat,
    QAudioOutput,
    QAudioSource,
    QMediaDevices,
    QMediaPlayer,
)
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
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.audio_editor import AudioEditResult, process_audio
from core.audio_utils import get_audio_info
from core.metadata import read_tags
from core.voice_cache import pcm_to_wav
from ui.vocal_separation_panel import WaveformView


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
    icon: str
    description: str
    operation: str
    fields: tuple[FieldSpec, ...] = ()
    multi_input: bool = False
    output_suffix: str = ".wav"


TOOLS = (
    ToolSpec("files", "文件管理", "▣", "查看当前素材、基础信息和编辑输出。", "files"),
    ToolSpec(
        "extract",
        "提取音频",
        "♫",
        "从视频或其他媒体中提取独立音轨。",
        "extract",
        output_suffix=".mp3",
    ),
    ToolSpec(
        "edit",
        "音频剪辑",
        "◩",
        "一次完成时间裁剪、淡入和淡出。",
        "edit",
        (
            FieldSpec("start", "开始时间", "float", 0.0, 0, 86400, " 秒"),
            FieldSpec("end", "结束时间（0=结尾）", "float", 0.0, 0, 86400, " 秒"),
            FieldSpec("fade_in", "淡入", "float", 0.0, 0, 60, " 秒"),
            FieldSpec("fade_out", "淡出", "float", 0.0, 0, 60, " 秒"),
        ),
    ),
    ToolSpec("record", "录音", "●", "使用 Windows 当前默认麦克风录制 WAV。", "record"),
    ToolSpec(
        "trim",
        "音频裁剪",
        "✂",
        "精确保留指定起止时间范围。",
        "trim",
        (
            FieldSpec("start", "开始时间", "float", 0.0, 0, 86400, " 秒"),
            FieldSpec("end", "结束时间（0=结尾）", "float", 0.0, 0, 86400, " 秒"),
        ),
    ),
    ToolSpec("concat", "音频拼接", "⫶", "按文件列表顺序首尾拼接。", "concat", multi_input=True),
    ToolSpec(
        "mix",
        "音频混合",
        "⇄",
        "多轨同时播放并混合，可设置各轨音量倍率。",
        "mix",
        (FieldSpec("volumes", "音量倍率", "text", "1,1"),),
        multi_input=True,
    ),
    ToolSpec(
        "fade",
        "淡入淡出",
        "◒",
        "为整段音频增加平滑的开头和结尾。",
        "fade",
        (
            FieldSpec("fade_in", "淡入时长", "float", 2.0, 0, 60, " 秒"),
            FieldSpec("fade_out", "淡出时长", "float", 2.0, 0, 60, " 秒"),
        ),
    ),
    ToolSpec(
        "speed_pitch",
        "变速变调",
        "↻",
        "独立调整播放速度和音高半音。",
        "speed_pitch",
        (
            FieldSpec("speed", "速度倍率", "float", 1.0, 0.25, 4.0, " ×"),
            FieldSpec("semitones", "音高", "float", 0.0, -12, 12, " 半音"),
        ),
    ),
    ToolSpec(
        "denoise",
        "音频降噪",
        "≋",
        "使用 FFT 降噪降低持续底噪。",
        "denoise",
        (FieldSpec("noise_floor", "噪声底限", "float", -25.0, -80, -20, " dB"),),
    ),
    ToolSpec(
        "normalize",
        "音量归一化",
        "▥",
        "按响度标准统一不同音频的主观音量。",
        "normalize",
        (
            FieldSpec("target_lufs", "目标响度", "float", -14.0, -30, -5, " LUFS"),
            FieldSpec("true_peak", "最大真峰值", "float", -1.0, -5, -0.1, " dBTP"),
        ),
    ),
    ToolSpec(
        "split",
        "音频分割",
        "◫",
        "按固定时长批量生成多个连续片段。",
        "split",
        (FieldSpec("segment_seconds", "每段时长", "float", 30.0, 1, 3600, " 秒"),),
    ),
    ToolSpec(
        "equalizer",
        "均衡器",
        "☷",
        "调整低频、中频和高频增益。",
        "equalizer",
        (
            FieldSpec("bass", "低频增益", "float", 0.0, -20, 20, " dB"),
            FieldSpec("middle", "中频增益", "float", 0.0, -20, 20, " dB"),
            FieldSpec("treble", "高频增益", "float", 0.0, -20, 20, " dB"),
        ),
    ),
    ToolSpec(
        "volume",
        "音频音量",
        "◖",
        "以分贝精确增大或减小音量。",
        "volume",
        (FieldSpec("gain_db", "音量增益", "float", 0.0, -60, 30, " dB"),),
    ),
    ToolSpec(
        "tags",
        "音频标记",
        "▤",
        "编辑标题、歌手、专辑、年份和轨道号。",
        "tags",
        (
            FieldSpec("title", "标题", "text", ""),
            FieldSpec("artist", "歌手", "text", ""),
            FieldSpec("album", "专辑", "text", ""),
            FieldSpec("year", "年份", "text", ""),
            FieldSpec("track", "轨道号", "text", ""),
        ),
        output_suffix=".mp3",
    ),
    ToolSpec(
        "more",
        "更多功能",
        "▦",
        "格式转换、声道转换、采样率调整或倒放。",
        "convert",
        (
            FieldSpec(
                "mode",
                "处理方式",
                "choice",
                "convert",
                choices=(("格式/声道转换", "convert"), ("音频倒放", "reverse")),
            ),
            FieldSpec(
                "channels",
                "输出声道",
                "choice",
                0,
                choices=(("保持原样", 0), ("单声道", 1), ("立体声", 2)),
            ),
            FieldSpec(
                "sample_rate",
                "采样率",
                "choice",
                0,
                choices=(
                    ("保持原样", 0),
                    ("16000 Hz", 16000),
                    ("44100 Hz", 44100),
                    ("48000 Hz", 48000),
                ),
            ),
        ),
    ),
)

TOOL_GROUPS = (
    ("基础编辑", ("edit", "trim", "split", "fade", "volume")),
    ("音质处理", ("denoise", "normalize", "equalizer", "speed_pitch")),
    ("多文件处理", ("concat", "mix")),
    ("文件与输出", ("files", "extract", "tags", "record", "more")),
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
                process_audio(
                    self.operation,
                    self.inputs,
                    self.output_path,
                    self.params,
                )
            )
        except (OSError, ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class AudioToolPage(QWidget):
    run_requested = pyqtSignal(object)
    back_requested = pyqtSignal()
    preview_requested = pyqtSignal(str)

    def __init__(self, spec: ToolSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.fields: dict[str, QWidget] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        heading_row = QHBoxLayout()
        back = QPushButton("← 返回工具")
        back.clicked.connect(self.back_requested)
        heading_row.addWidget(back)
        heading = QLabel(f"{self.spec.icon}  {self.spec.title}")
        heading.setStyleSheet("font-size:18px;font-weight:700")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        layout.addLayout(heading_row)
        note = QLabel(self.spec.description)
        note.setWordWrap(True)
        note.setStyleSheet("color:#667085;padding:4px 0 8px")
        layout.addWidget(note)

        input_group = QGroupBox("输入与输出")
        form = QFormLayout(input_group)
        if self.spec.multi_input:
            self.input_edit = QPlainTextEdit()
            self.input_edit.setPlaceholderText("每行一个音频文件，处理顺序从上到下")
            self.input_edit.setFixedHeight(100)
            add_inputs = QPushButton("添加音频文件")
            add_inputs.clicked.connect(self._browse_multi_inputs)
            input_box = QVBoxLayout()
            input_box.addWidget(self.input_edit)
            input_box.addWidget(add_inputs)
            form.addRow("输入文件:", input_box)
        else:
            self.input_edit = QLineEdit()
            browse = QPushButton("选择")
            browse.clicked.connect(self._browse_input)
            row = QHBoxLayout()
            row.addWidget(self.input_edit, 1)
            row.addWidget(browse)
            form.addRow("输入文件:", row)
        self.output_edit = QLineEdit()
        output_browse = QPushButton("选择")
        output_browse.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(output_browse)
        form.addRow("输出文件:", output_row)
        layout.addWidget(input_group)

        preview_row = QHBoxLayout()
        preview_input = QPushButton("试听输入")
        preview_input.clicked.connect(
            lambda: self.preview_requested.emit(self._primary_input())
        )
        preview_row.addWidget(preview_input)
        preview_output = QPushButton("试听输出")
        preview_output.clicked.connect(
            lambda: self.preview_requested.emit(self.output_edit.text().strip())
        )
        preview_row.addWidget(preview_output)
        open_output_dir = QPushButton("打开输出目录")
        open_output_dir.clicked.connect(self._open_output_folder)
        preview_row.addWidget(open_output_dir)
        preview_row.addStretch()
        layout.addLayout(preview_row)

        if self.spec.fields:
            parameter_group = QGroupBox("详细参数")
            parameter_form = QFormLayout(parameter_group)
            for field in self.spec.fields:
                widget = self._field_widget(field)
                self.fields[field.key] = widget
                parameter_form.addRow(field.label + ":", widget)
            layout.addWidget(parameter_group)

        self.run_button = QPushButton(f"执行：{self.spec.title}")
        self.run_button.setMinimumHeight(38)
        self.run_button.setStyleSheet(
            "QPushButton{background:#2878C8;color:white;font-weight:700;"
            "border-radius:5px;padding:8px}QPushButton:disabled{background:#AAB4C0}"
        )
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
            index = widget.findData(field.default)
            widget.setCurrentIndex(max(0, index))
            return widget
        widget = QLineEdit(str(field.default))
        return widget

    def set_primary_input(self, path: str):
        if self.spec.multi_input:
            if path and path not in self.input_edit.toPlainText().splitlines():
                self.input_edit.setPlainText(path)
        else:
            self.input_edit.setText(path)
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

    def _set_default_output(self, input_path: str):
        path = Path(input_path)
        folder = path.parent / "Echovault编辑输出"
        suffix = path.suffix if self.spec.operation == "tags" else self.spec.output_suffix
        self.output_edit.setText(
            str(folder / f"{path.stem}_{self.spec.key}{suffix}")
        )

    def inputs(self) -> list[str]:
        if self.spec.multi_input:
            return [
                value.strip()
                for value in self.input_edit.toPlainText().splitlines()
                if value.strip()
            ]
        return [self.input_edit.text().strip()]

    def _primary_input(self) -> str:
        values = self.inputs()
        return values[0] if values else ""

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
        return result

    def operation(self) -> str:
        if self.spec.key == "more":
            return str(self.params().get("mode") or "convert")
        return self.spec.operation

    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择输入媒体",
            "",
            "媒体文件 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus "
            "*.mp4 *.mkv *.mov *.avi);;所有文件 (*)",
        )
        if path:
            self.set_primary_input(path)

    def _browse_multi_inputs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择多个音频文件",
            "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;所有文件 (*)",
        )
        if paths:
            self.input_edit.setPlainText("\n".join(paths))
            self._set_default_output(paths[0])

    def _browse_output(self):
        current = self.output_edit.text().strip()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择输出文件",
            current,
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg *.opus);;所有文件 (*)",
        )
        if path:
            self.output_edit.setText(path)

    def _open_output_folder(self):
        output = Path(self.output_edit.text().strip())
        if not output.name:
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output.parent))


class AudioEditorPanel(QWidget):
    """Tool-catalog audio editor integrated with the current material selection."""

    output_created = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._song: dict = {}
        self._songs: list[dict] = []
        self._worker: AudioEditorWorker | None = None
        self._audio_source: QAudioSource | None = None
        self._audio_device = None
        self._record_file = None
        self._record_raw_path: Path | None = None
        self._record_output_path: Path | None = None
        self._record_seconds = 0
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        header = QHBoxLayout()
        title = QLabel("音频编辑")
        title.setStyleSheet("font-size:18px;font-weight:700;padding:4px")
        header.addWidget(title)
        header.addStretch()
        self.current_label = QLabel("未选择素材")
        self.current_label.setStyleSheet("color:#667085")
        header.addWidget(self.current_label)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.home_page = self._build_home()
        self.stack.addWidget(self.home_page)
        self.tool_pages: dict[str, AudioToolPage] = {}
        for spec in TOOLS:
            if spec.operation in {"files", "record"}:
                continue
            page = AudioToolPage(spec)
            page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home_page))
            page.run_requested.connect(self._run_tool)
            page.preview_requested.connect(self._preview_audio)
            self.tool_pages[spec.key] = page
            self.stack.addWidget(page)
        self.file_page = self._build_file_page()
        self.record_page = self._build_record_page()
        self.stack.addWidget(self.file_page)
        self.stack.addWidget(self.record_page)

        editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        editor_splitter.addWidget(self._build_tool_navigation())
        editor_splitter.addWidget(self._build_preview_workspace())
        parameter_frame = QFrame()
        parameter_frame.setObjectName("audioParameterPanel")
        parameter_layout = QVBoxLayout(parameter_frame)
        parameter_layout.setContentsMargins(10, 8, 10, 8)
        parameter_layout.addWidget(self.stack)
        editor_splitter.addWidget(parameter_frame)
        editor_splitter.setStretchFactor(0, 0)
        editor_splitter.setStretchFactor(1, 1)
        editor_splitter.setStretchFactor(2, 0)
        editor_splitter.setSizes([205, 620, 420])
        layout.addWidget(editor_splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("选择工具后可展开详细参数；所有处理都会生成新文件。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:11px;color:#667085")
        layout.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#audioToolRail {
                background:#F7F9FC;
                border:1px solid #DDE3EA;
                border-radius:11px;
            }
            QPushButton#audioToolButton {
                background:transparent;
                border:1px solid transparent;
                border-radius:8px;
                color:#334155;
                padding:7px 10px;
                text-align:left;
            }
            QPushButton#audioToolButton:hover {
                background:#EEF4FB;
            }
            QPushButton#audioToolButton:checked {
                background:#E7F1FC;
                border-color:#B7D1EC;
                color:#1F6FBB;
                font-weight:700;
            }
            QFrame#audioPreviewArea, QFrame#audioParameterPanel {
                background:#FFFFFF;
                border:1px solid #DDE3EA;
                border-radius:11px;
            }
            """
        )

    def _build_home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("选择一个编辑工具")
        heading.setStyleSheet("font-size:18px;font-weight:700;color:#14213D")
        layout.addWidget(heading)
        note = QLabel(
            "左侧按任务分类选择工具。当前素材、波形和播放位置会一直保留；"
            "右侧只切换当前工具的参数。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#667085;line-height:1.5")
        layout.addWidget(note)

        flow = QGroupBox("统一操作顺序")
        flow_layout = QVBoxLayout(flow)
        flow_layout.addWidget(QLabel("1　选择素材或时间范围"))
        flow_layout.addWidget(QLabel("2　在右侧设置参数"))
        flow_layout.addWidget(QLabel("3　试听输入与输出"))
        flow_layout.addWidget(QLabel("4　执行处理并生成新文件"))
        layout.addWidget(flow)

        safe_note = QLabel(
            "原文件不会被覆盖。默认结果保存到素材旁的 Echovault编辑输出，"
            "手机任务来源会自动加入待回传。"
        )
        safe_note.setWordWrap(True)
        safe_note.setStyleSheet(
            "background:#F0F7F2;color:#2F6B3C;padding:10px;border-radius:6px"
        )
        layout.addWidget(safe_note)
        layout.addStretch()
        return page

    def _build_tool_navigation(self):
        rail = QFrame()
        rail.setObjectName("audioToolRail")
        rail.setMinimumWidth(185)
        rail.setMaximumWidth(230)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(3)
        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.setExclusive(True)
        self.tool_buttons = {}
        by_key = {spec.key: spec for spec in TOOLS}
        for group_title, keys in TOOL_GROUPS:
            title = QLabel(group_title)
            title.setStyleSheet(
                "color:#64748B;font-size:11px;font-weight:700;padding:10px 7px 3px"
            )
            layout.addWidget(title)
            for key in keys:
                spec = by_key[key]
                button = QPushButton(f"{spec.icon}  {spec.title}")
                button.setObjectName("audioToolButton")
                button.setCheckable(True)
                button.setToolTip(spec.description)
                button.clicked.connect(
                    lambda _checked=False, target=key: self._open_tool(target)
                )
                self.tool_button_group.addButton(button)
                self.tool_buttons[key] = button
                layout.addWidget(button)
        layout.addStretch()
        return rail

    def _build_preview_workspace(self):
        frame = QFrame()
        frame.setObjectName("audioPreviewArea")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        heading = QLabel("素材与试听")
        heading.setStyleSheet("font-size:15px;font-weight:700;color:#14213D")
        layout.addWidget(heading)
        self.preview_material = QLabel("请先从素材工作区选择音乐或视频")
        self.preview_material.setWordWrap(True)
        self.preview_material.setStyleSheet(
            "background:#F7F9FC;color:#475569;padding:10px;border-radius:6px"
        )
        layout.addWidget(self.preview_material)

        ruler = QHBoxLayout()
        self.preview_start = QLabel("0:00")
        self.preview_end = QLabel("0:00")
        ruler.addWidget(self.preview_start)
        ruler.addStretch()
        ruler.addWidget(self.preview_end)
        layout.addLayout(ruler)
        self.waveform = WaveformView("#2F7DD1")
        self.waveform.setMinimumHeight(190)
        self.waveform.seek_requested.connect(self._seek_preview)
        layout.addWidget(self.waveform, 1)
        self.waveform_note = QLabel("WAV 素材会显示波形；其他格式仍可正常试听和处理。")
        self.waveform_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.waveform_note.setStyleSheet("color:#7B8796;font-size:11px")
        layout.addWidget(self.waveform_note)

        controls = QHBoxLayout()
        play = QPushButton("▶ 播放 / 暂停")
        play.clicked.connect(self._toggle_preview_playback)
        controls.addWidget(play)
        stop = QPushButton("■ 停止")
        stop.clicked.connect(self._player.stop)
        controls.addWidget(stop)
        self.preview_time = QLabel("0:00 / 0:00")
        self.preview_time.setStyleSheet("font-weight:700;color:#334155")
        controls.addWidget(self.preview_time)
        controls.addStretch()
        layout.addLayout(controls)

        self.preview_result = QLabel("尚未生成编辑结果")
        self.preview_result.setWordWrap(True)
        self.preview_result.setStyleSheet(
            "background:#F7F9FC;color:#667085;padding:10px;border-radius:6px"
        )
        layout.addWidget(self.preview_result)
        self._player.positionChanged.connect(self._preview_position_changed)
        self._player.durationChanged.connect(self._preview_duration_changed)
        return frame

    def _build_file_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        back = QPushButton("← 返回工具")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        layout.addWidget(back)
        heading = QLabel("▣ 文件管理")
        heading.setStyleSheet("font-size:18px;font-weight:700")
        layout.addWidget(heading)
        self.file_info = QLabel("请选择素材")
        self.file_info.setWordWrap(True)
        self.file_info.setStyleSheet("background:#F6F7FA;padding:10px;border-radius:6px")
        layout.addWidget(self.file_info)
        actions = QHBoxLayout()
        open_file = QPushButton("打开当前文件")
        open_file.clicked.connect(self._open_current_file)
        actions.addWidget(open_file)
        open_folder = QPushButton("打开所在目录")
        open_folder.clicked.connect(self._open_current_folder)
        actions.addWidget(open_folder)
        layout.addLayout(actions)
        layout.addWidget(QLabel("本次编辑结果"))
        self.output_list = QListWidget()
        self.output_list.itemDoubleClicked.connect(
            lambda item: os.startfile(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self.output_list, 1)
        return page

    def _build_record_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        back = QPushButton("← 返回工具")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        layout.addWidget(back)
        heading = QLabel("● 录音")
        heading.setStyleSheet("font-size:18px;font-weight:700")
        layout.addWidget(heading)
        note = QLabel("使用 Windows 默认麦克风录制 16-bit WAV；录音直接保存到编辑输出目录。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.record_path_edit = QLineEdit()
        browse = QPushButton("选择")
        browse.clicked.connect(self._browse_record_output)
        row = QHBoxLayout()
        row.addWidget(self.record_path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        self.record_button = QPushButton("开始录音")
        self.record_button.setMinimumHeight(44)
        self.record_button.clicked.connect(self._toggle_recording)
        layout.addWidget(self.record_button)
        self.record_status = QLabel("等待录音")
        self.record_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.record_status)
        layout.addStretch()
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(1000)
        self.record_timer.timeout.connect(self._update_record_time)
        return page

    def set_songs(self, songs: list[dict]):
        self._songs = [dict(song) for song in songs if song.get("path")]

    def show_song(self, song: dict):
        if not song or not song.get("path"):
            return
        self._song = dict(song)
        path = str(song["path"])
        self.current_label.setText(Path(path).name)
        self.preview_material.setText(f"{Path(path).name}\n{Path(path).parent}")
        if Path(path).suffix.lower() == ".wav":
            self.waveform.load_wav(path)
            self.waveform_note.setText("点击或拖动波形可以跳转试听位置。")
        else:
            self.waveform.samples = []
            self.waveform.set_playhead(0)
            self.waveform_note.setText(
                "当前格式可正常试听和处理；生成 WAV 结果后会显示波形。"
            )
        try:
            duration = float(get_audio_info(path).get("duration") or 0.0)
        except (OSError, RuntimeError, ValueError):
            duration = 0.0
        self.preview_start.setText("0:00")
        self.preview_end.setText(self._format_time(duration * 1000))
        self._refresh_file_info()
        for page in self.tool_pages.values():
            page.set_primary_input(path)
        self._set_default_record_path(path)

    def select_song(self, path: str):
        song = next((item for item in self._songs if item.get("path") == path), None)
        if song:
            self.show_song(song)

    def _open_tool(self, key: str):
        button = self.tool_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        if key == "files":
            self._refresh_file_info()
            self.stack.setCurrentWidget(self.file_page)
            return
        if key == "record":
            self.stack.setCurrentWidget(self.record_page)
            return
        page = self.tool_pages[key]
        if self._song.get("path"):
            page.set_primary_input(str(self._song["path"]))
        self.stack.setCurrentWidget(page)

    def _run_tool(self, page: AudioToolPage):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "音频编辑", "当前已有音频任务正在处理。")
            return
        inputs = page.inputs()
        output_path = page.output_edit.text().strip()
        if not output_path:
            QMessageBox.information(self, "音频编辑", "请先选择输出文件。")
            return
        try:
            operation = page.operation()
            params = page.params()
        except ValueError as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        params.pop("mode", None)
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
        self.status_label.setText(result.message)
        for output in result.outputs:
            item_text = f"{page.spec.title} · {Path(output).name}"
            self.output_list.addItem(item_text)
            item = self.output_list.item(self.output_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, output)
            self.output_created.emit(source_path, output, operation)
        latest = result.outputs[-1]
        self.preview_result.setText(
            f"最近结果：{Path(latest).name}\n双击文件管理中的结果可打开。"
        )
        if Path(latest).suffix.lower() == ".wav":
            self.waveform.load_wav(latest)
            self.waveform_note.setText("当前波形显示最近生成的 WAV 结果。")
        QMessageBox.information(
            self,
            "音频编辑完成",
            result.message + "\n\n" + "\n".join(result.outputs[:6]),
        )

    def _on_process_failed(self, page: AudioToolPage, message: str):
        page.run_button.setEnabled(True)
        self.progress.setVisible(False)
        self._worker = None
        self.status_label.setText(f"处理失败：{message}")
        QMessageBox.warning(self, "音频编辑失败", message)

    def _refresh_file_info(self):
        path = Path(self._song.get("path", ""))
        if not path.is_file():
            self.file_info.setText("请选择素材库中的音乐或视频文件。")
            return
        try:
            info = get_audio_info(str(path))
            duration = float(info.get("duration", 0))
            minutes, seconds = divmod(int(duration), 60)
            self.file_info.setText(
                f"文件：{path.name}\n目录：{path.parent}\n"
                f"时长：{minutes}:{seconds:02d}　采样率：{info.get('sample_rate', 0)} Hz　"
                f"声道：{info.get('channels', 0)}\n大小：{path.stat().st_size / 1024 / 1024:.2f} MB"
            )
        except Exception as exc:
            self.file_info.setText(f"文件：{path}\n无法读取音频信息：{exc}")

    def _open_current_file(self):
        path = self._song.get("path")
        if path and Path(path).exists():
            os.startfile(path)

    def _open_current_folder(self):
        path = self._song.get("path")
        if path and Path(path).exists():
            os.startfile(str(Path(path).parent))

    def _preview_audio(self, path: str):
        candidate = Path(path)
        if not candidate.is_file():
            QMessageBox.information(self, "试听", "所选音频文件尚不存在。")
            return
        source = QUrl.fromLocalFile(str(candidate.resolve()))
        if (
            self._player.source() == source
            and self._player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.pause()
            self.status_label.setText(f"试听已暂停：{candidate.name}")
            return
        if self._player.source() != source:
            self._player.setSource(source)
        self._player.play()
        self.status_label.setText(f"正在试听：{candidate.name}")

    def _toggle_preview_playback(self):
        source = str(self._song.get("path", ""))
        if not source:
            QMessageBox.information(self, "试听", "请先从素材工作区选择文件。")
            return
        self._preview_audio(source)

    def _seek_preview(self, ratio: float):
        duration = self._player.duration()
        if duration > 0:
            self._player.setPosition(int(duration * ratio))

    @staticmethod
    def _format_time(milliseconds: float) -> str:
        total_seconds = max(0, int(milliseconds / 1000))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _preview_position_changed(self, position: int):
        duration = self._player.duration()
        if duration > 0:
            self.waveform.set_playhead(position / duration)
        self.preview_time.setText(
            f"{self._format_time(position)} / {self._format_time(duration)}"
        )

    def _preview_duration_changed(self, duration: int):
        self.preview_end.setText(self._format_time(duration))
        self.preview_time.setText(
            f"{self._format_time(self._player.position())} / "
            f"{self._format_time(duration)}"
        )

    def _set_default_record_path(self, input_path: str):
        path = Path(input_path)
        output = path.parent / "Echovault编辑输出" / f"{path.stem}_record.wav"
        self.record_path_edit.setText(str(output))

    def _browse_record_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存录音",
            self.record_path_edit.text(),
            "WAV 音频 (*.wav)",
        )
        if path:
            self.record_path_edit.setText(path)

    def _toggle_recording(self):
        if self._audio_source is None:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        output = Path(self.record_path_edit.text().strip())
        if not output.name:
            QMessageBox.information(self, "录音", "请先选择录音输出文件。")
            return
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            QMessageBox.warning(self, "录音", "没有检测到可用麦克风。")
            return
        audio_format = QAudioFormat()
        audio_format.setSampleRate(44100)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            audio_format = device.preferredFormat()
        output.parent.mkdir(parents=True, exist_ok=True)
        self._record_output_path = output.with_suffix(".wav")
        self._record_raw_path = output.parent / f".{output.stem}.recording.pcm"
        try:
            self._record_file = self._record_raw_path.open("wb")
            self._audio_source = QAudioSource(device, audio_format, self)
            self._audio_device = self._audio_source.start()
            if self._audio_device is None:
                raise RuntimeError("麦克风无法开始录音。")
            self._audio_device.readyRead.connect(self._write_recording_data)
        except (OSError, RuntimeError) as exc:
            self._cleanup_recording()
            QMessageBox.warning(self, "录音", str(exc))
            return
        self._record_seconds = 0
        self.record_button.setText("停止录音 (0:00)")
        self.record_button.setStyleSheet("background:#C94545;color:white;font-weight:700")
        self.record_status.setText("正在录音…")
        self.record_timer.start()

    def _write_recording_data(self):
        if self._record_file is not None and self._audio_device is not None:
            self._record_file.write(bytes(self._audio_device.readAll()))

    def _stop_recording(self):
        if self._audio_source is None or self._record_raw_path is None:
            return
        self._write_recording_data()
        self.record_timer.stop()
        audio_format = self._audio_source.format()
        self._audio_source.stop()
        raw_path = self._record_raw_path
        output_path = self._record_output_path
        self._cleanup_recording()
        if not raw_path.is_file() or raw_path.stat().st_size == 0:
            raw_path.unlink(missing_ok=True)
            self.record_status.setText("没有录到声音")
            return
        if output_path is None:
            raw_path.unlink(missing_ok=True)
            self.record_status.setText("录音输出路径无效")
            return
        try:
            pcm_to_wav(
                raw_path,
                output_path,
                sample_rate=audio_format.sampleRate(),
                channels=audio_format.channelCount(),
                sample_width=audio_format.bytesPerSample(),
            )
            source = self._song.get("path", str(output_path))
            self.output_created.emit(str(source), str(output_path), "record")
            item_text = f"录音 · {output_path.name}"
            self.output_list.addItem(item_text)
            item = self.output_list.item(self.output_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, str(output_path))
            self.record_status.setText(f"已保存：{output_path}")
        except OSError as exc:
            QMessageBox.warning(self, "录音保存失败", str(exc))
        finally:
            raw_path.unlink(missing_ok=True)

    def _cleanup_recording(self):
        if self._record_file is not None:
            self._record_file.close()
        self._record_file = None
        self._audio_device = None
        if self._audio_source is not None:
            self._audio_source.deleteLater()
        self._audio_source = None
        self._record_raw_path = None
        self.record_button.setText("开始录音")
        self.record_button.setStyleSheet("")

    def _update_record_time(self):
        self._record_seconds += 1
        minutes, seconds = divmod(self._record_seconds, 60)
        self.record_button.setText(f"停止录音 ({minutes}:{seconds:02d})")
