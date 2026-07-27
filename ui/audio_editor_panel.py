"""Task-specific audio editing workspaces backed by FFmpeg and Mutagen."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.audio_editor import AudioEditResult, process_audio
from core.audio_utils import get_audio_info
from core.audio_waveform import extract_waveform_peaks
from core.output_paths import unique_output_path
from ui.audio_tool_workspaces import AudioToolWorkspace
from ui.playback_coordinator import PlaybackSession

WAVEFORM_CACHE_MAX_ITEMS = 8
LIVE_PREVIEW_MAX_ITEMS = 3
LIVE_PREVIEW_TOOLS = {
    "trim",
    "volume",
    "denoise",
    "normalize",
    "equalizer",
    "speed_pitch",
}
_WAVEFORM_CACHE: OrderedDict[tuple[str, int, int], tuple[object, float]] = OrderedDict()
_WAVEFORM_CACHE_LOCK = Lock()


def _source_signature(file_path: str) -> tuple[str, int, int]:
    path = Path(file_path).resolve()
    stat = path.stat()
    return str(path), int(stat.st_size), int(stat.st_mtime_ns)


def _cached_waveform(signature: tuple[str, int, int]):
    with _WAVEFORM_CACHE_LOCK:
        cached = _WAVEFORM_CACHE.get(signature)
        if cached is not None:
            _WAVEFORM_CACHE.move_to_end(signature)
        return cached


def _store_waveform(signature, peaks, duration: float) -> None:
    with _WAVEFORM_CACHE_LOCK:
        _WAVEFORM_CACHE[signature] = (tuple(peaks), float(duration))
        _WAVEFORM_CACHE.move_to_end(signature)
        while len(_WAVEFORM_CACHE) > WAVEFORM_CACHE_MAX_ITEMS:
            _WAVEFORM_CACHE.popitem(last=False)


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
        "精确选择片段，支持提取或删除，并在同一操作中调整音量、速度、变调与淡化。",
        "edit",
        (
            FieldSpec("gain_db", "音量增益", "float", 0.0, -24, 24, " dB"),
            FieldSpec("speed", "速度", "float", 1.0, 0.25, 4, " ×"),
            FieldSpec("semitones", "变调", "float", 0.0, -12, 12, " 半音"),
            FieldSpec("delay", "延迟", "float", 0.0, 0, 10, " 秒"),
            FieldSpec("fade_in", "淡入", "float", 0.0, 0, 30, " 秒"),
            FieldSpec("fade_out", "淡出", "float", 0.0, 0, 30, " 秒"),
        ),
    ),
    ToolSpec(
        "split",
        "分段导出",
        "在时间线上预览分段范围，并按固定时长连续生成编号文件。",
        "split",
        (FieldSpec("segment_seconds", "每段时长", "float", 30.0, 1, 3600, " 秒"),),
    ),
    ToolSpec(
        "volume",
        "增益",
        "使用独立增益工作台调整选区或整段响度，并可自动限制削波。",
        "volume",
        (FieldSpec("gain_db", "增益", "float", 0.0, -60, 30, " dB"),),
    ),
    ToolSpec(
        "denoise",
        "底噪抑制",
        "并排比较原始与处理后波形，选择降噪模式、强度和输出补偿。",
        "denoise",
        (
            FieldSpec("strength", "降噪强度", "float", 20.0, 1, 60),
            FieldSpec("output_gain", "输出增益", "float", 0.0, -12, 12, " dB"),
        ),
    ),
    ToolSpec(
        "normalize",
        "响度标准化",
        "通过播客、流媒体和广播目标卡设置 LUFS 与真峰值。",
        "normalize",
        (
            FieldSpec("target_lufs", "目标响度", "float", -14.0, -30, -5, " LUFS"),
            FieldSpec("true_peak", "最大真峰值", "float", -1.0, -5, -0.1, " dBTP"),
        ),
    ),
    ToolSpec(
        "equalizer",
        "八段均衡器",
        "拖动 60 Hz 到 16 kHz 的均衡曲线，并与其他页面参数实时叠加。",
        "equalizer",
    ),
    ToolSpec(
        "speed_pitch",
        "变速与变调",
        "使用专属波形、快速效果和独立滑杆调整速度与音高。",
        "speed_pitch",
        (
            FieldSpec("speed", "速度", "float", 1.0, 0.25, 4.0, " ×"),
            FieldSpec("semitones", "音高", "float", 0.0, -12, 12, " 半音"),
        ),
    ),
    ToolSpec(
        "concat",
        "顺序拼接",
        "在轨道时间线中组织素材顺序，逐条检查后首尾连接。",
        "concat",
        multi_input=True,
        selection_aware=False,
    ),
    ToolSpec(
        "mix",
        "多轨混音",
        "建立多轨工程，支持每轨静音、独奏、音量和左右声道合成。",
        "mix",
        multi_input=True,
        selection_aware=False,
    ),
    ToolSpec(
        "extract",
        "提取音轨",
        "选择媒体音轨、输出格式和质量，从视频或容器导出独立音频。",
        "extract",
        output_suffix=".mp3",
        selection_aware=False,
    ),
)


TOOL_GROUPS = (
    ("编辑工具", ("trim", "split", "volume")),
    ("修复与音色", ("denoise", "normalize", "equalizer", "speed_pitch")),
    ("合成与输出", ("concat", "mix", "extract")),
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
    completed = pyqtSignal(str, object, float, bool)
    failed = pyqtSignal(str, str)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        try:
            signature = _source_signature(self.file_path)
            cached = _cached_waveform(signature)
            if cached is not None:
                peaks, duration = cached
                self.completed.emit(self.file_path, peaks, duration, True)
                return
            try:
                duration = float(get_audio_info(self.file_path).get("duration") or 0.0)
            except (OSError, RuntimeError, ValueError):
                duration = 0.0
            peaks = extract_waveform_peaks(self.file_path)
            _store_waveform(signature, peaks, duration)
            self.completed.emit(self.file_path, peaks, duration, False)
        except (OSError, RuntimeError) as exc:
            self.failed.emit(self.file_path, str(exc))


class AudioEditorPanel(QWidget):
    """Audio editor whose tools each own a complete task-specific workspace."""

    output_created = pyqtSignal(str, str, str)
    save_available_changed = pyqtSignal(bool)
    position_changed_ms = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._song: dict = {}
        self._songs: list[dict] = []
        self._duration = 0.0
        self._selection = (0.0, 0.0)
        self._worker: AudioEditorWorker | None = None
        self._preview_worker: AudioEditorWorker | None = None
        self._preview_temp_dir = tempfile.TemporaryDirectory(
            prefix="echovault-live-preview-",
            ignore_cleanup_errors=True,
        )
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(240)
        self._preview_timer.timeout.connect(self._render_live_preview)
        self._preview_serial = 0
        self._preview_ready_serial = -1
        self._preview_pending = False
        self._preview_page: AudioToolWorkspace | None = None
        self._active_effect_keys: set[str] = set()
        self._effect_states: dict[str, dict] = {}
        self._preview_cache: OrderedDict[str, tuple[str, float, float]] = OrderedDict()
        self._live_preview_path = ""
        self._live_preview_start = 0.0
        self._live_preview_rate = 1.0
        self._waveform_worker: WaveformLoadWorker | None = None
        self._result_waveform_workers: list[WaveformLoadWorker] = []
        self._waveform_peaks: object = ()
        self._waveform_path = ""
        self._source_key: tuple[str, int, int] | None = None
        self._prepared_page_paths: dict[str, str] = {}
        self._waveform_page_paths: dict[str, str] = {}
        self._loading_page_paths: dict[str, str] = {}
        self._last_output = ""
        self._playing_path = ""
        self._special_pages: dict[str, QWidget] = {}
        self._special_controllers: dict[str, QWidget] = {}
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._playback_session = PlaybackSession(self._player)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_tool_navigation())
        self.stack = QStackedWidget()
        self.tool_pages: dict[str, AudioToolWorkspace] = {}
        for spec in TOOLS:
            page = AudioToolWorkspace(spec)
            page.run_requested.connect(self._run_tool)
            page.play_requested.connect(self._toggle_source_playback)
            page.result_play_requested.connect(
                lambda target=page: self._toggle_result_playback(target)
            )
            page.result_open_requested.connect(lambda target=page: self._open_result_folder(target))
            page.seek_requested.connect(self._seek_preview_seconds)
            page.selection_requested.connect(self._selection_changed)
            page.preview_parameters_changed.connect(
                lambda target=page: self._schedule_live_preview(target)
            )
            self.tool_pages[spec.key] = page
            self.stack.addWidget(page)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 1030])
        layout.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("选择左侧工具进入对应的独立工作台。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("audioEditorStatus")
        layout.addWidget(self.status_label)

        self._player.positionChanged.connect(self._preview_position_changed)
        self._player.playbackStateChanged.connect(self._playback_state_changed)
        self.setStyleSheet(
            """
            QFrame#audioToolRail {
                background:#FFFFFF; border:1px solid #DDE3EA; border-radius:11px;
            }
            QPushButton#audioToolButton {
                background:transparent; border:1px solid transparent;
                border-radius:7px; color:#334155; min-height:31px;
                padding:5px 10px; text-align:left;
            }
            QPushButton#audioToolButton:hover { background:#EEF4FB; }
            QPushButton#audioToolButton:checked {
                background:#E7F1FC; border-color:#B7D1EC;
                color:#1F6FBB; font-weight:700;
            }
            QLabel#audioToolGroupLabel {
                background:#F1F5F9; border-left:3px solid #8CB3D9;
                border-radius:4px; color:#526073; font-size:11px;
                font-weight:700; min-height:24px; padding:3px 8px;
            }
            QLabel#audioEditorStatus { color:#667085; font-size:11px; }
            """
        )
        self._open_tool("trim")

    def _build_tool_navigation(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(175)
        scroll.setMaximumWidth(215)
        rail = QFrame()
        rail.setObjectName("audioToolRail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(8, 10, 8, 10)
        rail_layout.setSpacing(3)
        title = QLabel("音频工作台")
        title.setStyleSheet("font-size:15px;font-weight:700;color:#14213D;padding:2px 6px")
        rail_layout.addWidget(title)
        subtitle = QLabel("整曲共享实时效果链")
        subtitle.setStyleSheet("color:#64748B;font-size:10px;padding:0 6px 5px")
        rail_layout.addWidget(subtitle)
        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.setExclusive(True)
        self.tool_buttons: dict[str, QPushButton] = {}
        self.tool_group_labels: list[QLabel] = []
        by_key = {spec.key: spec for spec in TOOLS}
        for group_index, (group_title, keys) in enumerate(TOOL_GROUPS):
            if group_index:
                rail_layout.addSpacing(7)
            group = QLabel(group_title)
            group.setObjectName("audioToolGroupLabel")
            self.tool_group_labels.append(group)
            rail_layout.addWidget(group)
            for key in keys:
                spec = by_key[key]
                button = QPushButton(spec.title)
                button.setObjectName("audioToolButton")
                button.setCheckable(True)
                button.setToolTip(spec.description)
                button.clicked.connect(lambda _checked=False, target=key: self._open_tool(target))
                self.tool_button_group.addButton(button)
                self.tool_buttons[key] = button
                rail_layout.addWidget(button)
        rail_layout.addStretch()
        self.tool_rail_layout = rail_layout
        scroll.setWidget(rail)
        self.tool_navigation_scroll = scroll
        return scroll

    def attach_vocal_separation_workspace(
        self,
        workspace: QWidget,
        controller: QWidget,
    ) -> None:
        """Expose Vocal Separation as a normal tool inside the audio editor rail."""

        key = "vocal_separation"
        if key in self._special_pages:
            return
        group = QLabel("智能处理")
        group.setObjectName("audioToolGroupLabel")
        self.tool_group_labels.append(group)
        button = QPushButton("人声分离")
        button.setObjectName("audioToolButton")
        button.setCheckable(True)
        button.setToolTip("分离人声与伴奏，并在同一工作台试听、调音和另存结果。")
        button.clicked.connect(
            lambda _checked=False: self._open_tool(key)
        )
        self.tool_button_group.addButton(button)
        self.tool_buttons[key] = button
        insert_at = max(0, self.tool_rail_layout.count() - 1)
        self.tool_rail_layout.insertSpacing(insert_at, 7)
        self.tool_rail_layout.insertWidget(insert_at + 1, group)
        self.tool_rail_layout.insertWidget(insert_at + 2, button)
        self._special_pages[key] = workspace
        self._special_controllers[key] = controller
        self.stack.addWidget(workspace)
        if hasattr(controller, "mix_saved"):
            controller.mix_saved.connect(
                lambda source, output: self.output_created.emit(
                    source, output, "vocal_mix"
                )
            )

    def set_songs(self, songs: list[dict]):
        self._songs = [dict(song) for song in songs if song.get("path")]

    def show_song(self, song: dict):
        if not song or not song.get("path"):
            return
        path = str(song["path"])
        try:
            source_key = _source_signature(path)
        except OSError:
            source_key = None
        if source_key is not None and source_key == self._source_key:
            self._song = dict(song)
            self._prepare_page(self.stack.currentWidget())
            self.status_label.setText(
                "当前素材已加载，无需重新分析波形。"
                if self._waveform_path == path
                else "当前素材正在分析波形，请稍候。"
            )
            return
        self._song = dict(song)
        self.save_available_changed.emit(True)
        self._invalidate_live_preview()
        self._active_effect_keys.clear()
        self._effect_states.clear()
        self._source_key = source_key
        self._duration = 0.0
        self._selection = (0.0, 0.0)
        self._waveform_peaks = ()
        self._waveform_path = ""
        self._prepared_page_paths.clear()
        self._waveform_page_paths.clear()
        self._loading_page_paths.clear()
        self._prepare_page(self.stack.currentWidget())
        self._start_waveform_load(path)
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self._playing_path = path
        self.status_label.setText("正在分析波形；各工具会在自己的工作台中显示素材。")

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

    def _waveform_loaded(
        self,
        path: str,
        peaks: list[tuple[float, float]],
        duration: float,
        from_cache: bool,
    ):
        if path != str(self._song.get("path", "")):
            return
        self._duration = max(0.0, float(duration))
        self._waveform_peaks = peaks
        self._waveform_path = path
        self._loading_page_paths.clear()
        self._prepare_page(self.stack.currentWidget())
        source = "缓存" if from_cache else "分析"
        self.status_label.setText(f"波形已从{source}就绪；其他工具会在首次打开时按需载入。")

    def _waveform_failed(self, path: str, message: str):
        if path == str(self._song.get("path", "")):
            self.status_label.setText(f"波形生成失败：{message}")

    def _selection_changed(self, start: float, end: float):
        start = max(0.0, min(self._duration, start))
        end = max(0.0, min(self._duration, end))
        start, end = sorted((start, end))
        self._selection = (start, end)
        page = self.stack.currentWidget()
        if isinstance(page, AudioToolWorkspace) and page._selection != (start, end):
            page.set_selection(start, end, self._duration)
        if end - start > 0.001:
            self.status_label.setText(
                f"当前选区 {self._format_time(start)} – {self._format_time(end)}，"
                f"共 {self._format_time(end - start)}。"
            )
        else:
            self.status_label.setText("未选择时间范围；支持选区的工具会处理整段素材。")

    def _schedule_live_preview(self, page: AudioToolWorkspace) -> None:
        """Persist this page's controls and rebuild the shared whole-song chain."""

        if (
            page.spec.key not in LIVE_PREVIEW_TOOLS
            or not self._song.get("path")
            or self._duration <= 0
        ):
            return
        try:
            state = page.params()
        except ValueError as exc:
            self.status_label.setText(f"实时试听参数无效：{exc}")
            return
        state.pop("selection_start", None)
        state.pop("selection_end", None)
        state.pop("crop_mode", None)
        self._effect_states[page.spec.key] = state
        self._active_effect_keys.add(page.spec.key)
        self._preview_page = page
        self._preview_serial += 1
        self._preview_ready_serial = -1
        self._apply_immediate_preview()
        self._preview_timer.start()
        self.status_label.setText(
            f"整曲实时效果链：已叠加 {len(self._active_effect_keys)} 个工具，正在更新…"
        )

    def _combined_effect_params(self) -> dict:
        """Flatten all changed workspaces into one cumulative FFmpeg chain."""

        result = {
            "gain_db": 0.0,
            "speed": 1.0,
            "semitones": 0.0,
            "delay": 0.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "bands": [],
            "balance": 0.0,
            "prevent_clipping": False,
        }
        trim = self._effect_states.get("trim", {})
        if "trim" in self._active_effect_keys:
            result["gain_db"] += float(trim.get("gain_db", 0.0))
            result["speed"] *= float(trim.get("speed", 1.0))
            result["semitones"] += float(trim.get("semitones", 0.0))
            result["delay"] = float(trim.get("delay", 0.0))
            result["fade_in"] = float(trim.get("fade_in", 0.0))
            result["fade_out"] = float(trim.get("fade_out", 0.0))
        volume = self._effect_states.get("volume", {})
        if "volume" in self._active_effect_keys:
            result["gain_db"] += float(volume.get("gain_db", 0.0))
            result["prevent_clipping"] = bool(volume.get("prevent_clipping", False))
        denoise = self._effect_states.get("denoise", {})
        if "denoise" in self._active_effect_keys:
            result["gain_db"] += float(denoise.get("output_gain", 0.0))
            result["denoise"] = {
                "enabled": True,
                "mode": denoise.get("denoise_mode", 1),
                "strength": denoise.get("strength", 20.0),
            }
        normalize = self._effect_states.get("normalize", {})
        if "normalize" in self._active_effect_keys:
            result["normalize"] = {
                "enabled": True,
                "target_lufs": normalize.get("target_lufs", -14.0),
                "true_peak": normalize.get("true_peak", -1.0),
            }
        equalizer = self._effect_states.get("equalizer", {})
        if "equalizer" in self._active_effect_keys:
            result["bands"] = list(equalizer.get("bands") or [0.0] * 8)
            result["balance"] = float(equalizer.get("balance", 0.0))
        speed_pitch = self._effect_states.get("speed_pitch", {})
        if "speed_pitch" in self._active_effect_keys:
            result["speed"] *= float(speed_pitch.get("speed", 1.0))
            result["semitones"] += float(speed_pitch.get("semitones", 0.0))
        return result

    def _apply_immediate_preview(self) -> None:
        """Apply controls supported natively while the rendered preview catches up."""

        params = self._combined_effect_params()
        source = str(self._song.get("path", ""))
        if not source:
            return
        if self._playing_path == self._live_preview_path:
            position = self._live_preview_start + (
                self._player.position() / 1000.0 * self._live_preview_rate
            )
        elif self._playing_path == source:
            position = self._player.position() / 1000.0
        else:
            position = (
                self._selection[0]
                if self._selection[1] - self._selection[0] > 0.001
                else 0.0
            )
        url = QUrl.fromLocalFile(str(Path(source).resolve()))
        if self._player.source() != url:
            self._player.setSource(url)
        self._playing_path = source
        self._player.setPosition(int(max(0.0, position) * 1000))
        speed = float(params.get("speed", 1.0) or 1.0)
        self._player.setPlaybackRate(max(0.25, min(4.0, speed)))
        gain_db = float(params.get("gain_db", params.get("output_gain", 0.0)) or 0.0)
        linear_gain = math.pow(10.0, gain_db / 20.0)
        self._audio_output.setVolume(max(0.0, min(1.0, linear_gain)))
        self._playback_session.play(self._player)

    def _preview_range(self) -> tuple[float, float]:
        return 0.0, self._duration

    def _render_live_preview(self) -> None:
        page = self._preview_page
        if page is None or not self._active_effect_keys:
            return
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_pending = True
            return
        source = str(self._song.get("path", ""))
        if not source:
            return
        inputs = [source]
        params = self._combined_effect_params()
        start, end = self._preview_range()
        if end <= start:
            return
        params["_preview"] = True
        operation = "effect_chain"
        serial = self._preview_serial
        speed = float(params.get("speed", 1.0) or 1.0)
        signature = json.dumps(
            {
                "source": self._source_key,
                "tools": sorted(self._active_effect_keys),
                "operation": operation,
                "inputs": inputs,
                "params": params,
            },
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
        cached = self._preview_cache.get(signature)
        if cached and Path(cached[0]).is_file():
            self._preview_cache.move_to_end(signature)
            self._activate_live_preview(
                page,
                cached[0],
                cached[1],
                cached[2],
                serial,
                from_cache=True,
            )
            return
        output_path = str(
            Path(self._preview_temp_dir.name)
            / f"whole-song-chain-{serial}.flac"
        )
        self._preview_worker = AudioEditorWorker(
            operation,
            inputs,
            output_path,
            params,
            self,
        )
        self._preview_worker.completed.connect(
            lambda result, target=page, token=serial, key=signature, offset=start, rate=speed: (
                self._live_preview_completed(
                    target,
                    result,
                    token,
                    key,
                    offset,
                    rate,
                )
            )
        )
        self._preview_worker.failed.connect(self._live_preview_failed)
        self._preview_worker.start()

    def _live_preview_completed(
        self,
        page: AudioToolWorkspace,
        result: AudioEditResult,
        serial: int,
        signature: str,
        start: float,
        rate: float,
    ) -> None:
        self._preview_worker = None
        path = result.outputs[-1]
        self._preview_cache[signature] = (path, start, rate)
        self._preview_cache.move_to_end(signature)
        while len(self._preview_cache) > LIVE_PREVIEW_MAX_ITEMS:
            _key, (expired, _start, _rate) = self._preview_cache.popitem(last=False)
            try:
                Path(expired).unlink(missing_ok=True)
            except OSError:
                pass
        if serial == self._preview_serial:
            current = self.stack.currentWidget()
            target = current if isinstance(current, AudioToolWorkspace) else page
            self._activate_live_preview(target, path, start, rate, serial)
        if self._preview_pending:
            self._preview_pending = False
            self._preview_timer.start(20)

    def _activate_live_preview(
        self,
        page: AudioToolWorkspace,
        path: str,
        start: float,
        rate: float,
        serial: int,
        *,
        from_cache: bool = False,
    ) -> None:
        source_position = self._current_source_position()
        was_playing = (
            self._player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )
        self._reset_direct_preview()
        self._live_preview_path = path
        self._live_preview_start = start
        self._live_preview_rate = max(0.01, rate)
        self._preview_ready_serial = serial
        self._playing_path = path
        self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        preview_position = max(0.0, (source_position - start) / self._live_preview_rate)
        self._player.setPosition(int(preview_position * 1000))
        if was_playing:
            self._playback_session.play(self._player)
        source = "缓存" if from_cache else "新效果"
        self.status_label.setText(
            f"整曲实时效果链已更新（{source}，"
            f"已叠加 {len(self._active_effect_keys)} 个工具）。"
        )
        page.set_playing(was_playing)

    def _live_preview_failed(self, message: str) -> None:
        self._preview_worker = None
        self.status_label.setText(
            f"实时试听暂不可用：{message}。音量与速度仍会即时响应。"
        )
        if self._preview_pending:
            self._preview_pending = False
            self._preview_timer.start(20)

    def _reset_direct_preview(self) -> None:
        self._player.setPlaybackRate(1.0)
        self._audio_output.setVolume(1.0)

    def _current_source_position(self) -> float:
        position = self._player.position() / 1000.0
        if self._playing_path == self._live_preview_path and self._live_preview_path:
            return self._live_preview_start + position * self._live_preview_rate
        return position

    def _live_preview_is_ready(
        self,
        page: AudioToolWorkspace | None = None,
    ) -> bool:
        target = page or self.stack.currentWidget()
        return (
            isinstance(target, AudioToolWorkspace)
            and self._preview_ready_serial == self._preview_serial
            and bool(self._live_preview_path)
            and Path(self._live_preview_path).is_file()
        )

    def _configure_direct_preview(self, _page: AudioToolWorkspace) -> None:
        """Apply the subset QMediaPlayer can change without rendering."""

        params = self._combined_effect_params()
        speed = float(params.get("speed", 1.0) or 1.0)
        self._player.setPlaybackRate(max(0.25, min(4.0, speed)))
        gain_db = float(
            params.get("gain_db", params.get("output_gain", 0.0)) or 0.0
        )
        linear_gain = math.pow(10.0, gain_db / 20.0)
        self._audio_output.setVolume(max(0.0, min(1.0, linear_gain)))

    def _invalidate_live_preview(self) -> None:
        self._preview_timer.stop()
        self._preview_serial += 1
        self._preview_ready_serial = -1
        self._preview_pending = False
        self._preview_page = None
        self._reset_direct_preview()
        if self._playing_path == self._live_preview_path:
            self._player.pause()
        self._live_preview_path = ""

    def timeline_select_all(self):
        page = self.stack.currentWidget()
        if isinstance(page, AudioToolWorkspace) and getattr(page, "timeline", None):
            page.timeline.select_all()

    def timeline_clear_selection(self):
        page = self.stack.currentWidget()
        if isinstance(page, AudioToolWorkspace) and getattr(page, "timeline", None):
            page.timeline.clear_selection()

    def _open_tool(self, key: str):
        page = self.tool_pages.get(key) or self._special_pages.get(key)
        if page is None:
            return
        previous = self.stack.currentWidget()
        if not isinstance(page, AudioToolWorkspace) and previous is not page and (
            self._preview_page is not None or self._live_preview_path
        ):
            self._invalidate_live_preview()
        self.tool_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(page)
        if isinstance(page, AudioToolWorkspace) and self._song.get("path"):
            self._prepare_page(page)
        if isinstance(page, AudioToolWorkspace):
            page.set_playhead(self._current_source_position())
            playing = (
                self._player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState
            )
            page.set_playing(
                playing and self._playing_path == self._song.get("path")
            )
            page.set_result_playing(
                playing and self._playing_path == page._result_path
            )
            self.timeline = getattr(page, "timeline", None)
            title = page.spec.title
        else:
            self._player.pause()
            self.timeline = None
            title = "人声分离"
        if isinstance(page, AudioToolWorkspace):
            count = len(self._active_effect_keys)
            suffix = f"；当前已叠加 {count} 个实时效果" if count else ""
            self.status_label.setText(f"已进入“{title}”工作台{suffix}。")
        else:
            self.status_label.setText(f"已进入“{title}”独立工作台。")

    def _prepare_page(self, page: AudioToolWorkspace | None) -> None:
        if not isinstance(page, AudioToolWorkspace):
            return
        path = str(self._song.get("path", ""))
        if not path:
            return
        key = page.spec.key
        page.setUpdatesEnabled(False)
        try:
            if self._prepared_page_paths.get(key) != path:
                if page.track_editor is not None:
                    page.track_editor.set_paths([path])
                page.set_primary_input(path)
                self._prepared_page_paths[key] = path
            if self._waveform_path == path:
                if self._waveform_page_paths.get(key) != path:
                    page.set_audio(self._waveform_peaks, self._duration)
                    self._waveform_page_paths[key] = path
            elif self._loading_page_paths.get(key) != path:
                page.set_loading(self._duration)
                self._loading_page_paths[key] = path
            page.set_selection(*self._selection, self._duration)
        finally:
            page.setUpdatesEnabled(True)
            page.update()

    def _run_tool(self, page: AudioToolWorkspace):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "音频编辑", "当前已有音频任务正在处理。")
            return
        inputs = page.inputs()
        if not inputs:
            QMessageBox.information(self, "音频编辑", "请先选择素材。")
            return
        if page.spec.multi_input and len(inputs) < 2:
            QMessageBox.information(self, page.spec.title, "请至少添加两条音频轨道。")
            return
        if page.spec.key == "trim" and not page.has_selection():
            QMessageBox.information(self, "裁剪与淡化", "请先在波形中选择要处理的时间范围。")
            return
        output_path = page.output_edit.text().strip()
        if not output_path:
            QMessageBox.information(self, "音频编辑", "请先选择输出文件。")
            return
        safe_output_path = unique_output_path(output_path, inputs)
        if safe_output_path != output_path:
            page.output_edit.setText(safe_output_path)
            output_path = safe_output_path
            self.status_label.setText(
                f"为保护源文件和已有结果，已改为新文件："
                f"{Path(output_path).name}"
            )
        try:
            params = page.params()
        except ValueError as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        self._invalidate_live_preview()
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

    def save_active_as_new_file(self) -> None:
        """Save the cumulative whole-song chain without overwriting the source."""

        page = self.stack.currentWidget()
        if isinstance(page, AudioToolWorkspace):
            if not self._active_effect_keys:
                self._run_tool(page)
                return
            if self._worker is not None and self._worker.isRunning():
                QMessageBox.information(self, "音频编辑", "当前已有音频任务正在处理。")
                return
            source = str(self._song.get("path", ""))
            if not source:
                QMessageBox.information(self, "音频编辑", "请先选择素材。")
                return
            output_path = page.output_edit.text().strip()
            if not output_path:
                QMessageBox.information(self, "音频编辑", "请先选择输出文件。")
                return
            output_path = unique_output_path(output_path, [source])
            page.output_edit.setText(output_path)
            self._invalidate_live_preview()
            page.run_button.setEnabled(False)
            self.progress.setVisible(True)
            self.status_label.setText(
                f"正在保存整曲效果链（{len(self._active_effect_keys)} 个工具）…"
            )
            self._worker = AudioEditorWorker(
                "effect_chain",
                [source],
                output_path,
                self._combined_effect_params(),
                self,
            )
            self._worker.completed.connect(
                lambda result, target=page, original=source: self._on_process_completed(
                    target,
                    result,
                    original,
                    "effect_chain",
                )
            )
            self._worker.failed.connect(
                lambda message, target=page: self._on_process_failed(target, message)
            )
            self._worker.start()
            return
        for key, special_page in self._special_pages.items():
            if page is special_page:
                controller = self._special_controllers[key]
                if hasattr(controller, "save_mix_as_new_file"):
                    controller.save_mix_as_new_file()
                return
        QMessageBox.information(self, "保存为新文件", "请先选择音频编辑工具。")

    def _on_process_completed(
        self,
        page: AudioToolWorkspace,
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
        page.set_result(self._last_output, result.message)
        self.status_label.setText(result.message)
        if page.spec.key == "denoise":
            self._load_processed_waveform(page, self._last_output)

    def _load_processed_waveform(self, page: AudioToolWorkspace, path: str):
        worker = WaveformLoadWorker(path, self)
        self._result_waveform_workers.append(worker)
        worker.completed.connect(
            lambda output, peaks, duration, _cached, target=page: self._processed_waveform_loaded(
                target, output, peaks, duration
            )
        )
        worker.finished.connect(
            lambda current=worker: (
                self._result_waveform_workers.remove(current)
                if current in self._result_waveform_workers
                else None
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @staticmethod
    def _processed_waveform_loaded(
        page: AudioToolWorkspace,
        _path: str,
        peaks: list[tuple[float, float]],
        duration: float,
    ):
        page.set_processed_audio(peaks, duration or page._duration)

    def _on_process_failed(self, page: AudioToolWorkspace, message: str):
        page.run_button.setEnabled(True)
        self.progress.setVisible(False)
        self._worker = None
        self.status_label.setText(f"处理失败：{message}")
        QMessageBox.warning(self, "音频编辑失败", message)

    def _toggle_source_playback(self):
        source = str(self._song.get("path", ""))
        if not source:
            QMessageBox.information(self, "试听", "请先从素材工作区选择文件。")
            return
        page = self.stack.currentWidget()
        preview_path = (
            self._live_preview_path
            if isinstance(page, AudioToolWorkspace)
            and self._live_preview_is_ready(page)
            else ""
        )
        target_path = preview_path or source
        if (
            self._playing_path == target_path
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.pause()
            return
        source_position = self._current_source_position()
        url = QUrl.fromLocalFile(str(Path(target_path).resolve()))
        if self._player.source() != url:
            self._player.setSource(url)
        self._playing_path = target_path
        if preview_path:
            self._reset_direct_preview()
            preview_position = max(
                0.0,
                (source_position - self._live_preview_start)
                / self._live_preview_rate,
            )
            self._player.setPosition(int(preview_position * 1000))
        else:
            if isinstance(page, AudioToolWorkspace):
                self._configure_direct_preview(page)
            if self._selection[1] - self._selection[0] > 0.001:
                current = source_position
                if not self._selection[0] <= current < self._selection[1]:
                    source_position = self._selection[0]
            self._player.setPosition(int(max(0.0, source_position) * 1000))
        if not preview_path and self._selection[1] - self._selection[0] > 0.001:
            current = self._player.position() / 1000.0
            if not self._selection[0] <= current < self._selection[1]:
                self._player.setPosition(int(self._selection[0] * 1000))
        self._playback_session.play(self._player)

    def _toggle_result_playback(self, page: AudioToolWorkspace):
        result_path = page._result_path
        if not result_path or not Path(result_path).is_file():
            return
        if (
            self._playing_path == result_path
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.pause()
            return
        self._reset_direct_preview()
        self._playing_path = result_path
        self._player.setSource(QUrl.fromLocalFile(str(Path(result_path).resolve())))
        self._playback_session.play(self._player)

    @staticmethod
    def _open_result_folder(page: AudioToolWorkspace):
        if page._result_path and Path(page._result_path).exists():
            os.startfile(str(Path(page._result_path).parent))

    def _seek_preview_seconds(self, seconds: float):
        source = str(self._song.get("path", ""))
        if not source:
            return
        seconds = max(0.0, min(self._duration, seconds))
        page = self.stack.currentWidget()
        use_live_preview = self._live_preview_is_ready(
            page if isinstance(page, AudioToolWorkspace) else None
        )
        preview_end = self._duration
        if (
            self._playing_path == self._live_preview_path
            and self._player.duration() > 0
        ):
            preview_end = self._live_preview_start + (
                self._player.duration() / 1000.0 * self._live_preview_rate
            )
        use_live_preview = bool(
            use_live_preview
            and self._live_preview_start <= seconds <= preview_end
        )
        target_path = self._live_preview_path if use_live_preview else source
        url = QUrl.fromLocalFile(str(Path(target_path).resolve()))
        if self._player.source() != url:
            self._player.setSource(url)
        self._playing_path = target_path
        if use_live_preview:
            self._reset_direct_preview()
            position = (seconds - self._live_preview_start) / self._live_preview_rate
        else:
            if isinstance(page, AudioToolWorkspace):
                self._configure_direct_preview(page)
            position = seconds
        self._player.setPosition(int(max(0.0, position) * 1000))
        if isinstance(page, AudioToolWorkspace):
            page.set_playhead(seconds)
        self.position_changed_ms.emit(int(seconds * 1000))

    def _preview_position_changed(self, position: int):
        source = str(self._song.get("path", ""))
        seconds = position / 1000.0
        source_seconds = seconds
        if self._playing_path == self._live_preview_path and self._live_preview_path:
            source_seconds = (
                self._live_preview_start + seconds * self._live_preview_rate
            )
        page = self.stack.currentWidget()
        if isinstance(page, AudioToolWorkspace) and (
            self._playing_path == source
            or self._playing_path == self._live_preview_path
        ):
            page.set_playhead(source_seconds)
        self.position_changed_ms.emit(int(max(0.0, source_seconds) * 1000))
        if self._playing_path == source:
            if (
                self._selection[1] - self._selection[0] > 0.001
                and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                and source_seconds >= self._selection[1]
            ):
                self._player.pause()
                self._player.setPosition(int(self._selection[0] * 1000))

    def _playback_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        source = str(self._song.get("path", ""))
        page = self.stack.currentWidget()
        if isinstance(page, AudioToolWorkspace):
            page.set_playing(
                playing
                and self._playing_path in {source, self._live_preview_path}
            )
            page.set_result_playing(playing and self._playing_path == page._result_path)

    @staticmethod
    def _format_time(seconds: float) -> str:
        milliseconds = int(round(max(0.0, seconds) * 1000))
        minutes, remainder = divmod(milliseconds, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{minutes}:{secs:02d}.{millis:03d}"
