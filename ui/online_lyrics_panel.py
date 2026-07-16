"""Online lyric search controls and the separate left-side comparison workspace."""

from dataclasses import dataclass, replace
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap, QTextCharFormat, QTextCursor, QTextFormat
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.cover_art import (
    CoverArtMatch,
    download_cover_art,
    image_mime_type,
    search_cover_art,
)
from core.metadata import COVER_EDITABLE_FORMATS, read_cover_art
from core.online_lyrics import (
    LyricsMatch,
    active_lrc_line_index,
    calibrate_lrc_with_reference,
    compare_lyrics,
    media_search_metadata,
    search_lrclib,
    simplify_lyrics_content,
    timed_text_entries,
)
from ui.system_audio import apply_system_default_audio


@dataclass(frozen=True)
class OnlineLyricsAction:
    """All content needed to safely apply one comparison choice."""

    match: LyricsMatch
    local_content: str
    online_content: str


@dataclass(frozen=True)
class CoverApplyAction:
    image_data: bytes
    mime_type: str
    source: str


class LRCLIBSearchWorker(QThread):
    completed = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, track_name, artist_name, album_name, duration, parent=None):
        super().__init__(parent)
        self.track_name = track_name
        self.artist_name = artist_name
        self.album_name = album_name
        self.duration = duration

    def run(self):
        try:
            results = search_lrclib(
                self.track_name,
                artist_name=self.artist_name,
                album_name=self.album_name,
                duration=self.duration,
            )
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class CoverSearchWorker(QThread):
    completed = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, track_name, artist_name, album_name, parent=None):
        super().__init__(parent)
        self.track_name = track_name
        self.artist_name = artist_name
        self.album_name = album_name

    def run(self):
        try:
            self.completed.emit(
                search_cover_art(
                    self.track_name,
                    artist_name=self.artist_name,
                    album_name=self.album_name,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class CoverDownloadWorker(QThread):
    completed = pyqtSignal(object, bytes, str)
    failed = pyqtSignal(str)

    def __init__(self, match: CoverArtMatch, parent=None):
        super().__init__(parent)
        self.match = match

    def run(self):
        try:
            data, mime_type = download_cover_art(self.match.image_url)
            self.completed.emit(self.match, data, mime_type)
        except Exception as exc:
            self.failed.emit(str(exc))


class LyricsCalibrationWorker(QThread):
    completed = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(
        self, lrc_path, match, ai_settings, local_content=None, parent=None
    ):
        super().__init__(parent)
        self.lrc_path = lrc_path
        self.match = match
        self.ai_settings = ai_settings
        self.local_content = local_content

    def run(self):
        reference = self.match.synced_lyrics or self.match.plain_lyrics
        try:
            output, backup = calibrate_lrc_with_reference(
                self.lrc_path,
                reference,
                ai_settings=self.ai_settings,
                track_name=self.match.track_name,
                artist_name=self.match.artist_name,
                local_content=self.local_content,
            )
            self.completed.emit(str(output), str(backup))
        except Exception as exc:
            self.failed.emit(str(exc))


class LyricsCompareEditor(QPlainTextEdit):
    """Read-only lyric view that enters edit mode on double click."""

    edit_requested = pyqtSignal(object)

    def mouseDoubleClickEvent(self, event):
        self.edit_requested.emit(self)
        super().mouseDoubleClickEvent(event)

    def highlight_at(self, position_seconds: float) -> int:
        line_index = active_lrc_line_index(self.toPlainText(), position_seconds)
        if line_index < 0:
            self.setExtraSelections([])
            return -1
        block = self.document().findBlockByNumber(line_index)
        if not block.isValid():
            self.setExtraSelections([])
            return -1
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(block)
        style = QTextCharFormat()
        style.setBackground(QColor("#fff3a0"))
        style.setFontWeight(QFont.Weight.Bold.value)
        style.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.format = style
        self.setExtraSelections([selection])
        if self.isReadOnly():
            self.setTextCursor(selection.cursor)
            self.centerCursor()
        return line_index


class OnlineLyricsComparisonPane(QWidget):
    """Main-window left pane: local/online lyrics side by side, player below."""

    content_changed = pyqtSignal()
    playback_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._song: dict = {}
        self._seeking = False
        self._setup_ui()
        self._setup_player()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        heading = QLabel("歌词核对")
        heading.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        layout.addWidget(heading)
        self.song_label = QLabel("请在右侧选择歌曲并搜索在线歌词")
        self.song_label.setWordWrap(True)
        self.song_label.setStyleSheet("color:#666;padding:2px 4px")
        layout.addWidget(self.song_label)

        comparison = QSplitter(Qt.Orientation.Horizontal)
        local_group = QGroupBox("左：本地识别歌词（双击修改）")
        local_layout = QVBoxLayout(local_group)
        self.local_editor = LyricsCompareEditor()
        self.local_editor.setReadOnly(True)
        self.local_editor.setPlaceholderText("本地尚未识别；请使用右侧“识别本地歌词”")
        self.local_editor.edit_requested.connect(self._begin_editing)
        self.local_editor.textChanged.connect(self.content_changed.emit)
        local_layout.addWidget(self.local_editor)
        comparison.addWidget(local_group)

        online_group = QGroupBox("右：在线匹配歌词（双击修改）")
        online_layout = QVBoxLayout(online_group)
        self.online_editor = LyricsCompareEditor()
        self.online_editor.setReadOnly(True)
        self.online_editor.setPlaceholderText("右侧搜索并选择结果后显示在线歌词")
        self.online_editor.edit_requested.connect(self._begin_editing)
        self.online_editor.textChanged.connect(self.content_changed.emit)
        online_layout.addWidget(self.online_editor)
        comparison.addWidget(online_group)
        comparison.setChildrenCollapsible(False)
        comparison.setSizes([1, 1])
        layout.addWidget(comparison, 1)

        player_group = QGroupBox("播放器（播放本地素材，同步滚动两侧歌词）")
        player_group.setMinimumHeight(82)
        player_layout = QHBoxLayout(player_group)
        self.play_button = QPushButton("播放")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_playback)
        player_layout.addWidget(self.play_button)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderPressed.connect(self._on_seek_started)
        self.position_slider.sliderReleased.connect(self._on_seek_finished)
        self.position_slider.sliderMoved.connect(self._preview_seek_position)
        player_layout.addWidget(self.position_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        player_layout.addWidget(self.time_label)
        layout.addWidget(player_group)

        self.status_label = QLabel("双击任一侧会暂停；右侧按钮使用当前编辑内容。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.status_label)

    def _setup_player(self):
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.errorOccurred.connect(
            lambda _error, message: self.status_label.setText(
                f"播放器错误：{message or '无法播放当前素材'}"
            )
        )
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self._apply_system_audio_output)
        self._apply_system_audio_output()

    def _apply_system_audio_output(self):
        if hasattr(self, "audio_output"):
            available = apply_system_default_audio(self.audio_output)
            self.audio_output.setVolume(0.8)
            return available
        return False

    def show_song(self, song: dict):
        if not song or not song.get("path"):
            return
        self.player.stop()
        self._song = dict(song)
        path = Path(song["path"])
        self._song["lrc_path"] = str(path.with_suffix(".lrc"))
        self.song_label.setText(path.name)
        self.reload_local_lyrics()
        self.set_online_content("")
        if path.is_file():
            self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self.play_button.setEnabled(True)
        else:
            self.player.setSource(QUrl())
            self.play_button.setEnabled(False)

    def reload_local_lyrics(self):
        lrc_path = Path(self._song.get("lrc_path", ""))
        try:
            content = lrc_path.read_text(encoding="utf-8") if lrc_path.is_file() else ""
        except (OSError, UnicodeError) as exc:
            content = ""
            self.status_label.setText(f"无法读取本地歌词：{exc}")
        self.local_editor.setPlainText(content)
        self.local_editor.setReadOnly(True)

    def set_online_content(self, content: str):
        self.online_editor.setPlainText(content)
        self.online_editor.setReadOnly(True)

    def local_content(self) -> str:
        return self.local_editor.toPlainText()

    def online_content(self) -> str:
        return self.online_editor.toPlainText()

    def _begin_editing(self, editor: LyricsCompareEditor):
        self.player.pause()
        editor.setReadOnly(False)
        editor.setFocus()
        side = "本地" if editor is self.local_editor else "在线"
        self.status_label.setText(
            f"已暂停并进入{side}歌词编辑；右侧采用、合并或校准会使用当前内容。"
        )

    @staticmethod
    def _format_milliseconds(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.local_editor.setReadOnly(True)
            self.online_editor.setReadOnly(True)
            if not self._apply_system_audio_output():
                self.status_label.setText("未检测到音频输出设备，请检查 Windows 声音设置。")
                return
            self.audio_output.setVolume(0.8)
            self.status_label.setText("正在通过 Windows 系统默认输出播放本地素材。")
            self.player.play()
            self.playback_started.emit()

    def pause_playback(self):
        self.player.pause()

    def _on_playback_state_changed(self, state):
        self.play_button.setText(
            "暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "播放"
        )

    def _on_duration_changed(self, duration: int):
        self.position_slider.setRange(0, max(0, duration))
        self.time_label.setText(
            f"{self._format_milliseconds(self.player.position())} / "
            f"{self._format_milliseconds(duration)}"
        )

    def _highlight_both(self, position: int):
        seconds = position / 1000.0
        self.local_editor.highlight_at(seconds)
        self.online_editor.highlight_at(seconds)

    def _on_position_changed(self, position: int):
        if not self._seeking:
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(position)
            self.position_slider.blockSignals(False)
        self.time_label.setText(
            f"{self._format_milliseconds(position)} / "
            f"{self._format_milliseconds(self.player.duration())}"
        )
        self._highlight_both(position)

    def _on_seek_started(self):
        self._seeking = True

    def _on_seek_finished(self):
        self._seeking = False
        self.player.setPosition(self.position_slider.value())

    def _preview_seek_position(self, position: int):
        self.time_label.setText(
            f"{self._format_milliseconds(position)} / "
            f"{self._format_milliseconds(self.player.duration())}"
        )
        self._highlight_both(position)


class OnlineLyricsPanel(QWidget):
    """Right pane: song/search results and all recognition/application actions."""

    action_requested = pyqtSignal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs: list[dict] = []
        self._song: dict = {}
        self._matches: list[LyricsMatch] = []
        self._cover_matches: list[CoverArtMatch] = []
        self._cover_image_data = b""
        self._cover_mime_type = ""
        self._cover_source = ""
        self._cover_busy = False
        self._duration = 0.0
        self._comparison: OnlineLyricsComparisonPane | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        heading_row = QHBoxLayout()
        heading = QLabel("在线歌词与封面匹配")
        heading.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        self.transcribe_button = QPushButton("开始识别")
        self.transcribe_button.clicked.connect(
            lambda: self._request_action("transcribe_local")
        )
        heading_row.addWidget(self.transcribe_button)
        self.search_button = QPushButton("搜索 LRCLIB")
        self.search_button.clicked.connect(self._start_search)
        heading_row.addWidget(self.search_button)
        layout.addLayout(heading_row)

        form = QFormLayout()
        self.source_filter = QComboBox()
        self.source_filter.addItem("全部素材", "all")
        self.source_filter.addItem("音乐库", "music")
        self.source_filter.addItem("视频库", "video")
        self.source_filter.currentIndexChanged.connect(self._rebuild_song_selector)
        form.addRow("素材来源:", self.source_filter)
        self.song_selector = QComboBox()
        self.song_selector.setMinimumContentsLength(24)
        self.song_selector.currentIndexChanged.connect(self._on_song_selected)
        form.addRow("选择歌曲:", self.song_selector)
        self.track_input = QLineEdit()
        self.artist_input = QLineEdit()
        self.album_input = QLineEdit()
        form.addRow("搜索歌名:", self.track_input)
        metadata_row = QHBoxLayout()
        metadata_row.addWidget(QLabel("歌手"))
        metadata_row.addWidget(self.artist_input)
        metadata_row.addWidget(QLabel("专辑"))
        metadata_row.addWidget(self.album_input)
        form.addRow("搜索信息:", metadata_row)
        layout.addLayout(form)

        self.current_file_label = QLabel("请先选择歌曲")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.current_file_label)

        cover_group = QGroupBox("封面匹配")
        cover_layout = QHBoxLayout(cover_group)
        self.cover_preview = QLabel("暂无封面")
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setFixedSize(112, 112)
        self.cover_preview.setStyleSheet(
            "QLabel{border:1px solid #CCD3DA;background:#F5F6F7;color:#888;}"
        )
        cover_layout.addWidget(self.cover_preview)
        cover_controls = QVBoxLayout()
        self.cover_selector = QComboBox()
        self.cover_selector.setIconSize(QSize(42, 42))
        self.cover_selector.setPlaceholderText("搜索后选择在线封面")
        self.cover_selector.currentIndexChanged.connect(
            self._on_cover_result_selected
        )
        cover_controls.addWidget(self.cover_selector)
        cover_buttons = QHBoxLayout()
        self.search_cover_button = QPushButton("搜索在线封面")
        self.search_cover_button.clicked.connect(self._start_cover_search)
        cover_buttons.addWidget(self.search_cover_button)
        self.local_cover_button = QPushButton("选择本地封面")
        self.local_cover_button.clicked.connect(self._choose_local_cover)
        cover_buttons.addWidget(self.local_cover_button)
        cover_controls.addLayout(cover_buttons)
        self.apply_cover_button = QPushButton("写入音频标签")
        self.apply_cover_button.clicked.connect(self._request_cover_apply)
        cover_controls.addWidget(self.apply_cover_button)
        self.cover_status_label = QLabel(
            "支持在线匹配或本地 JPEG/PNG；写入时不改变音频内容。"
        )
        self.cover_status_label.setWordWrap(True)
        self.cover_status_label.setStyleSheet("font-size:11px;color:#666")
        cover_controls.addWidget(self.cover_status_label)
        cover_controls.addStretch()
        cover_layout.addLayout(cover_controls, 1)
        layout.addWidget(cover_group)

        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["匹配", "歌名", "歌手", "时长", "同步"]
        )
        self.results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.currentCellChanged.connect(self._on_result_selected)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.results_table, 1)

        self.comparison_label = QLabel(
            "选择搜索结果后，歌词会显示在左侧对照区的右半栏。"
        )
        self.comparison_label.setWordWrap(True)
        self.comparison_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.comparison_label)

        action_group = QGroupBox("识别、应用与校准")
        action_grid = QGridLayout(action_group)
        self.use_local_button = QPushButton("直接应用左侧本地歌词")
        self.use_local_button.clicked.connect(lambda: self._request_action("use_local"))
        action_grid.addWidget(self.use_local_button, 0, 0)
        self.use_online_button = QPushButton("直接应用右侧在线歌词")
        self.use_online_button.clicked.connect(
            lambda: self._request_action("use_online")
        )
        action_grid.addWidget(self.use_online_button, 0, 1)
        self.merge_local_button = QPushButton("左时间轴 + 右文字")
        self.merge_local_button.clicked.connect(
            lambda: self._request_action("merge_local_timeline")
        )
        action_grid.addWidget(self.merge_local_button, 1, 0)
        self.merge_online_button = QPushButton("右时间轴 + 左文字")
        self.merge_online_button.clicked.connect(
            lambda: self._request_action("merge_online_timeline")
        )
        action_grid.addWidget(self.merge_online_button, 1, 1)
        self.calibrate_button = QPushButton("AI 核对并校准左侧歌词")
        self.calibrate_button.clicked.connect(
            lambda: self._request_action("calibrate")
        )
        action_grid.addWidget(self.calibrate_button, 2, 0, 1, 2)
        layout.addWidget(action_group)

        self.status_label = QLabel("LRCLIB 只提供歌词，不提供歌曲音频。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.status_label)
        self._refresh_action_state()

    def bind_comparison_pane(self, comparison: OnlineLyricsComparisonPane):
        if self._comparison is comparison:
            return
        self._comparison = comparison
        comparison.content_changed.connect(self._on_comparison_content_changed)
        if self._song:
            comparison.show_song(self._song)
        self._refresh_action_state()

    def _on_comparison_content_changed(self):
        self._refresh_action_state()
        if self._selected_match() is not None:
            self.refresh_local_comparison()

    def _local_content(self) -> str:
        return self._comparison.local_content() if self._comparison is not None else ""

    def _online_content(self) -> str:
        return self._comparison.online_content() if self._comparison is not None else ""

    def set_songs(self, songs: list[dict]):
        self._songs = [dict(song) for song in songs if song.get("path")]
        self._rebuild_song_selector()

    def _rebuild_song_selector(self, *_args):
        current_path = self._song.get("path", "")
        source = self.source_filter.currentData()
        visible_songs = [
            song
            for song in self._songs
            if source == "all" or song.get("material_type", "music") == source
        ]
        self.song_selector.blockSignals(True)
        self.song_selector.clear()
        for song in visible_songs:
            name = Path(song.get("name") or song["path"]).stem
            material_type = song.get("material_type", "music")
            type_name = "视频" if material_type == "video" else "音乐"
            self.song_selector.addItem(f"[{type_name}] {name}", song)
        selected_index = next(
            (
                index
                for index, song in enumerate(visible_songs)
                if song.get("path") == current_path
            ),
            -1,
        )
        self.song_selector.setCurrentIndex(selected_index)
        self.song_selector.blockSignals(False)

    def _on_song_selected(self, index: int):
        song = self.song_selector.itemData(index) if index >= 0 else None
        if song:
            self.show_song(song, sync_selector=False)

    def show_song(self, song: dict, *, sync_selector: bool = True):
        if not song or not song.get("path"):
            return
        self._song = dict(song)
        path = Path(song["path"])
        lrc_path = path.with_suffix(".lrc")
        self._song["lrc_path"] = str(lrc_path)
        self._song["has_lrc"] = lrc_path.is_file()
        self._matches = []
        self._cover_matches = []
        self.cover_selector.blockSignals(True)
        self.cover_selector.clear()
        self.cover_selector.blockSignals(False)
        if sync_selector:
            index = next(
                (
                    item
                    for item in range(self.song_selector.count())
                    if (self.song_selector.itemData(item) or {}).get("path") == str(path)
                ),
                -1,
            )
            if index >= 0:
                self.song_selector.blockSignals(True)
                self.song_selector.setCurrentIndex(index)
                self.song_selector.blockSignals(False)

        metadata = media_search_metadata(path)
        self.track_input.setText(metadata.track_name)
        self.artist_input.setText(metadata.artist_name)
        self.album_input.setText(metadata.album_name)
        self._duration = metadata.duration
        duration_text = self._format_duration(metadata.duration) if metadata.duration else "未知"
        self.current_file_label.setText(f"{path.name} · {duration_text}")
        self.results_table.setRowCount(0)
        if self._comparison is not None:
            self._comparison.show_song(self._song)
        self.reload_cover()
        self.comparison_label.setText(
            "搜索并选择结果后，歌词会显示在左侧对照区的右半栏。"
        )
        self.status_label.setText("已选择本地素材，可以搜索公开歌词库。")
        self._refresh_action_state()

    def reload_cover(self):
        media_path = self._song.get("path", "")
        if not media_path:
            self._clear_cover_preview("暂无封面")
            self._refresh_cover_state()
            return
        try:
            cover = read_cover_art(str(media_path))
        except Exception as exc:
            self._clear_cover_preview("无法读取")
            self.cover_status_label.setText(f"无法读取内嵌封面：{exc}")
            self._refresh_cover_state()
            return
        if cover:
            self._set_cover_preview(
                cover[0],
                cover[1],
                "当前音频内嵌封面",
            )
        else:
            self._clear_cover_preview("暂无封面")
            self.cover_status_label.setText(
                "当前音频没有内嵌封面，可在线搜索或选择本地图片。"
            )
        self._refresh_cover_state()

    def _set_cover_preview(
        self,
        image_data: bytes,
        mime_type: str,
        source: str,
    ) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_data):
            self.cover_status_label.setText("所选图片无法解析。")
            return False
        self._cover_image_data = bytes(image_data)
        self._cover_mime_type = image_mime_type(image_data, mime_type)
        self._cover_source = source
        self.cover_preview.setText("")
        self.cover_preview.setPixmap(
            pixmap.scaled(
                self.cover_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.cover_status_label.setText(source)
        self._refresh_cover_state()
        return True

    def _clear_cover_preview(self, text: str):
        self._cover_image_data = b""
        self._cover_mime_type = ""
        self._cover_source = ""
        self.cover_preview.clear()
        self.cover_preview.setText(text)

    def _is_cover_editable_song(self) -> bool:
        path = Path(self._song.get("path", ""))
        return (
            bool(path.name)
            and self._song.get("material_type", "music") != "video"
            and path.suffix.lower() in COVER_EDITABLE_FORMATS
        )

    def _refresh_cover_state(self):
        editable = self._is_cover_editable_song()
        self.search_cover_button.setEnabled(editable and not self._cover_busy)
        self.local_cover_button.setEnabled(editable and not self._cover_busy)
        self.cover_selector.setEnabled(
            editable and not self._cover_busy and bool(self._cover_matches)
        )
        self.apply_cover_button.setEnabled(
            editable and not self._cover_busy and bool(self._cover_image_data)
        )

    def _start_cover_search(self):
        if not self._is_cover_editable_song():
            self.cover_status_label.setText(
                "当前素材格式不支持写入封面，请选择音乐文件。"
            )
            return
        track_name = self.track_input.text().strip()
        album_name = self.album_input.text().strip()
        if not track_name and not album_name:
            self.cover_status_label.setText("请先填写歌名或专辑名。")
            return
        self._cover_busy = True
        self._refresh_cover_state()
        self.cover_status_label.setText("正在搜索 MusicBrainz 与 Cover Art Archive…")
        self._cover_search_worker = CoverSearchWorker(
            track_name,
            self.artist_input.text().strip(),
            album_name,
            self,
        )
        self._cover_search_worker.completed.connect(self._show_cover_results)
        self._cover_search_worker.failed.connect(self._show_cover_error)
        self._cover_search_worker.start()

    def _show_cover_results(self, matches: list):
        self._cover_busy = False
        self._cover_matches = list(matches)
        self.cover_selector.blockSignals(True)
        self.cover_selector.clear()
        for match in self._cover_matches:
            date = f" · {match.first_release_date[:4]}" if match.first_release_date else ""
            artist = f" · {match.artist_name}" if match.artist_name else ""
            self.cover_selector.addItem(
                f"{match.score:.0f}% · {match.title}{artist}{date}",
                match,
            )
        self.cover_selector.blockSignals(False)
        if self._cover_matches:
            self.cover_status_label.setText(
                f"找到 {len(self._cover_matches)} 张封面，正在载入第一张…"
            )
            self.cover_selector.setCurrentIndex(0)
            self._on_cover_result_selected(0)
        else:
            self.cover_status_label.setText(
                "没有找到可用封面，可调整歌名/专辑名或选择本地图片。"
            )
        self._refresh_cover_state()

    def _show_cover_error(self, message: str):
        self._cover_busy = False
        self.cover_status_label.setText(f"封面搜索失败：{message}")
        self._refresh_cover_state()

    def _on_cover_result_selected(self, index: int):
        match = self.cover_selector.itemData(index) if index >= 0 else None
        if not isinstance(match, CoverArtMatch):
            return
        self._cover_busy = True
        self._cover_image_data = b""
        self.cover_status_label.setText(f"正在下载封面：{match.title}…")
        self._refresh_cover_state()
        self._cover_download_worker = CoverDownloadWorker(match, self)
        self._cover_download_worker.completed.connect(self._cover_downloaded)
        self._cover_download_worker.failed.connect(self._show_cover_error)
        self._cover_download_worker.start()

    def _cover_downloaded(
        self,
        match: CoverArtMatch,
        image_data: bytes,
        mime_type: str,
    ):
        current = self.cover_selector.currentData()
        if not isinstance(current, CoverArtMatch):
            return
        if current.release_group_id != match.release_group_id:
            return
        self._cover_busy = False
        self._set_cover_preview(
            image_data,
            mime_type,
            f"在线封面：{match.title} · {match.artist_name or '未知歌手'}",
        )
        self._refresh_cover_state()

    def _choose_local_cover(self):
        if not self._is_cover_editable_song():
            return
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择本地封面",
            "",
            "封面图片 (*.jpg *.jpeg *.png);;所有文件 (*)",
        )
        if not file_path:
            return
        try:
            image_data = Path(file_path).read_bytes()
        except OSError as exc:
            self.cover_status_label.setText(f"无法读取本地封面：{exc}")
            return
        if len(image_data) > 20 * 1024 * 1024:
            self.cover_status_label.setText("本地封面不能超过 20 MB。")
            return
        mime_type = image_mime_type(image_data)
        if mime_type not in {"image/jpeg", "image/png"}:
            self.cover_status_label.setText("请选择 JPEG 或 PNG 图片。")
            return
        self.cover_selector.blockSignals(True)
        self.cover_selector.setCurrentIndex(-1)
        self.cover_selector.blockSignals(False)
        self._set_cover_preview(
            image_data,
            mime_type,
            f"本地封面：{Path(file_path).name}",
        )

    def _request_cover_apply(self):
        media_path = self._song.get("path")
        if not media_path or not self._cover_image_data:
            return
        self.action_requested.emit(
            str(media_path),
            CoverApplyAction(
                image_data=self._cover_image_data,
                mime_type=self._cover_mime_type,
                source=self._cover_source,
            ),
            "apply_cover",
        )

    def reload_local_lyrics(self):
        path = Path(self._song.get("path", ""))
        self._song["lrc_path"] = str(path.with_suffix(".lrc"))
        self._song["has_lrc"] = path.with_suffix(".lrc").is_file()
        if self._comparison is not None:
            self._comparison.reload_local_lyrics()
        self._refresh_action_state()

    @staticmethod
    def _format_duration(duration: float) -> str:
        minutes, seconds = divmod(int(round(duration)), 60)
        return f"{minutes}:{seconds:02d}"

    def _start_search(self):
        track_name = self.track_input.text().strip()
        if not track_name:
            self.status_label.setText("请先选择歌曲或填写搜索歌名。")
            return
        self.search_button.setEnabled(False)
        self.status_label.setText("正在搜索 LRCLIB…")
        self._search_worker = LRCLIBSearchWorker(
            track_name,
            self.artist_input.text().strip(),
            self.album_input.text().strip(),
            self._duration,
            self,
        )
        self._search_worker.completed.connect(self._show_results)
        self._search_worker.failed.connect(self._show_search_error)
        self._search_worker.start()

    def _show_results(self, matches: list):
        self.search_button.setEnabled(True)
        self._matches = list(matches)
        self.results_table.setRowCount(len(self._matches))
        for row, match in enumerate(self._matches):
            values = [
                f"{match.score:.0f}%",
                match.track_name,
                match.artist_name,
                self._format_duration(match.duration),
                "有" if match.has_synced_lyrics else "纯文本",
            ]
            for column, value in enumerate(values):
                self.results_table.setItem(row, column, QTableWidgetItem(value))
        if self._matches:
            self.results_table.setCurrentCell(0, 0)
            self.status_label.setText(
                f"找到 {len(self._matches)} 条结果；选择后可直接应用或校准。"
            )
        else:
            if self._comparison is not None:
                self._comparison.set_online_content("")
            self.status_label.setText("没有找到匹配结果，请调整歌名或歌手。")
        self._refresh_action_state()

    def _show_search_error(self, message: str):
        self.search_button.setEnabled(True)
        self.status_label.setText(f"搜索失败：{message}")

    def _selected_match(self) -> LyricsMatch | None:
        row = self.results_table.currentRow()
        return self._matches[row] if 0 <= row < len(self._matches) else None

    def _on_result_selected(self, *_args):
        match = self._selected_match()
        if match is None:
            if self._comparison is not None:
                self._comparison.set_online_content("")
            self._refresh_action_state()
            return
        if self._comparison is not None:
            self._comparison.set_online_content(
                simplify_lyrics_content(
                    match.synced_lyrics or match.plain_lyrics
                )
            )
        self.refresh_local_comparison()
        self._refresh_action_state()

    def refresh_local_comparison(self):
        match = self._selected_match()
        if match is None:
            return
        local_content = self._local_content()
        online_content = self._online_content()
        if not timed_text_entries(local_content):
            self.comparison_label.setText(
                "本地暂无同步 LRC；可先点击识别，或直接应用在线同步歌词。"
            )
            return
        comparison = compare_lyrics(local_content, online_content)
        self.comparison_label.setText(
            f"文字相似度 {comparison['similarity'] * 100:.1f}% · "
            f"本地 {comparison['local_lines']} 行 / 在线 {comparison['reference_lines']} 行"
        )

    def _refresh_action_state(self):
        local_content = self._local_content()
        online_content = self._online_content()
        has_local_timeline = bool(timed_text_entries(local_content))
        has_online_timeline = bool(timed_text_entries(online_content))
        has_online_text = bool(online_content.strip())
        has_song = bool(self._song.get("path"))
        self.transcribe_button.setText(
            "重新识别" if has_local_timeline else "开始识别"
        )
        self.transcribe_button.setEnabled(has_song)
        self.use_local_button.setEnabled(has_local_timeline)
        self.use_online_button.setEnabled(has_online_timeline)
        self.merge_local_button.setEnabled(has_local_timeline and has_online_text)
        self.merge_online_button.setEnabled(
            has_online_timeline and bool(local_content.strip())
        )
        self.calibrate_button.setEnabled(has_local_timeline and has_online_text)
        self._refresh_cover_state()

    def _request_action(self, action: str):
        media_path = self._song.get("path")
        if not media_path:
            return
        if action == "transcribe_local":
            self.action_requested.emit(str(media_path), None, action)
            return
        match = self._selected_match()
        if match is None:
            return
        online_content = self._online_content()
        if timed_text_entries(online_content):
            edited_match = replace(match, synced_lyrics=online_content)
        else:
            edited_match = replace(match, synced_lyrics="", plain_lyrics=online_content)
        payload = OnlineLyricsAction(
            match=edited_match,
            local_content=self._local_content(),
            online_content=online_content,
        )
        self.action_requested.emit(str(media_path), payload, action)
