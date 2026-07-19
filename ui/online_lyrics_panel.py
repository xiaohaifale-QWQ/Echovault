"""Online lyrics, cover discovery, synchronized playback, and verification."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic

from PyQt6.QtCore import QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
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
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.cover_art import (
    CoverArtMatch,
    download_cover_art,
    image_mime_type,
    search_cover_art_fast,
)
from core.metadata import COVER_EDITABLE_FORMATS, read_cover_art, read_tags
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

SEARCH_CACHE_TTL_SECONDS = 600.0
_LYRICS_SEARCH_CACHE: dict[tuple, tuple[float, list]] = {}
_COVER_SEARCH_CACHE: dict[tuple, tuple[float, list]] = {}
_THUMBNAIL_CACHE: dict[str, tuple[bytes, str]] = {}


def _cached_result(cache: dict, key: tuple):
    cached = cache.get(key)
    if cached is None:
        return None
    created_at, value = cached
    if monotonic() - created_at > SEARCH_CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return list(value)


def _store_result(cache: dict, key: tuple, value: list):
    if len(cache) >= 32:
        oldest = min(cache, key=lambda item: cache[item][0])
        cache.pop(oldest, None)
    cache[key] = (monotonic(), list(value))


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


@dataclass(frozen=True)
class TagApplyAction:
    """Common audio tags edited from the online lyrics workspace."""

    values: dict[str, str]


class LRCLIBSearchWorker(QThread):
    quick_result = pyqtSignal(list)
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
            key = (
                self.track_name.casefold().strip(),
                self.artist_name.casefold().strip(),
                self.album_name.casefold().strip(),
                round(float(self.duration)),
            )
            results = _cached_result(_LYRICS_SEARCH_CACHE, key)
            if results is None:
                results = search_lrclib(
                    self.track_name,
                    artist_name=self.artist_name,
                    album_name=self.album_name,
                    duration=self.duration,
                    timeout=10.0,
                    quick_callback=self.quick_result.emit,
                )
                _store_result(_LYRICS_SEARCH_CACHE, key, results)
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
            key = (
                self.track_name.casefold().strip(),
                self.artist_name.casefold().strip(),
                self.album_name.casefold().strip(),
            )
            results = _cached_result(_COVER_SEARCH_CACHE, key)
            if results is None:
                results = search_cover_art_fast(
                    self.track_name,
                    artist_name=self.artist_name,
                    album_name=self.album_name,
                    timeout=6.0,
                )
                _store_result(_COVER_SEARCH_CACHE, key, results)
            self.completed.emit(results)
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


class CoverThumbnailWorker(QThread):
    thumbnail_ready = pyqtSignal(int, object, bytes, str)
    thumbnail_failed = pyqtSignal(object)

    def __init__(self, matches: list[CoverArtMatch], parent=None):
        super().__init__(parent)
        self.matches = list(matches)

    def run(self):
        def download(index_match):
            index, match = index_match
            cached = _THUMBNAIL_CACHE.get(match.thumbnail_url)
            if cached is not None:
                return index, match, cached[0], cached[1]
            try:
                data, mime_type = download_cover_art(match.thumbnail_url)
            except Exception:
                return index, match, None, None
            if len(_THUMBNAIL_CACHE) >= 64:
                _THUMBNAIL_CACHE.pop(next(iter(_THUMBNAIL_CACHE)), None)
            _THUMBNAIL_CACHE[match.thumbnail_url] = (data, mime_type)
            return index, match, data, mime_type

        if not self.matches:
            return
        with ThreadPoolExecutor(max_workers=min(4, len(self.matches))) as executor:
            futures = [executor.submit(download, item) for item in enumerate(self.matches)]
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue
                index, match, data, mime_type = result
                if data is None:
                    self.thumbnail_failed.emit(match)
                else:
                    self.thumbnail_ready.emit(index, match, data, mime_type)


class LyricsCalibrationWorker(QThread):
    completed = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, lrc_path, match, ai_settings, local_content=None, parent=None):
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


class OnlineLyricsResultPane(QWidget):
    """Selected online lyrics with a synchronized local-media player."""

    content_changed = pyqtSignal()
    playback_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._song: dict = {}
        self._seeking = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = LyricsCompareEditor()
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("点击“一键搜索”，最佳在线同步歌词会显示在这里")
        self.editor.edit_requested.connect(self._begin_editing)
        self.editor.textChanged.connect(self.content_changed)
        layout.addWidget(self.editor, 1)

        self.player_group = QGroupBox("播放器 · 同步滚动在线歌词")
        player_layout = QHBoxLayout(self.player_group)
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
        layout.addWidget(self.player_group)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self._apply_system_audio_output)
        self._apply_system_audio_output()

    def take_player_group(self) -> QGroupBox:
        """Move the transport outside the editor pane so it can span its workspace."""
        self.layout().removeWidget(self.player_group)
        self.player_group.setParent(None)
        return self.player_group

    def show_song(self, song: dict):
        self.player.stop()
        self._song = dict(song or {})
        path = Path(self._song.get("path", ""))
        if path.is_file():
            self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self.play_button.setEnabled(True)
        else:
            self.player.setSource(QUrl())
            self.play_button.setEnabled(False)
        self.set_content("")

    def set_content(self, content: str):
        if self.editor.toPlainText() == content:
            return
        self.editor.blockSignals(True)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)
        self.editor.setReadOnly(True)

    def content(self) -> str:
        return self.editor.toPlainText()

    def pause_playback(self):
        self.player.pause()

    def _apply_system_audio_output(self):
        available = apply_system_default_audio(self.audio_output)
        self.audio_output.setVolume(0.8)
        return available

    def _begin_editing(self, editor: LyricsCompareEditor):
        self.player.pause()
        editor.setReadOnly(False)
        editor.setFocus()

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        self.editor.setReadOnly(True)
        if self._apply_system_audio_output():
            self.player.play()
            self.playback_started.emit()

    def _on_playback_state_changed(self, state):
        self.play_button.setText(
            "暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "播放"
        )

    def _on_duration_changed(self, duration: int):
        self.position_slider.setRange(0, max(0, duration))
        self._set_time_label(self.player.position(), duration)

    def _on_position_changed(self, position: int):
        if not self._seeking:
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(position)
            self.position_slider.blockSignals(False)
        self._set_time_label(position, self.player.duration())
        self.editor.highlight_at(position / 1000.0)

    def _on_seek_started(self):
        self._seeking = True

    def _on_seek_finished(self):
        self._seeking = False
        self.player.setPosition(self.position_slider.value())

    def _preview_seek_position(self, position: int):
        self._set_time_label(position, self.player.duration())
        self.editor.highlight_at(position / 1000.0)

    def _set_time_label(self, position: int, duration: int):
        self.time_label.setText(
            f"{self._format_milliseconds(position)} / {self._format_milliseconds(duration)}"
        )

    @staticmethod
    def _format_milliseconds(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"


class OnlineLyricsPanel(QWidget):
    """Right pane: song/search results and all recognition/application actions."""

    action_requested = pyqtSignal(str, object, str)
    playback_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs: list[dict] = []
        self._song: dict = {}
        self._matches: list[LyricsMatch] = []
        self._cover_matches: list[CoverArtMatch] = []
        self._cover_items: dict[str, QListWidgetItem] = {}
        self._cover_thumbnail_workers: list[CoverThumbnailWorker] = []
        self._cover_busy = False
        self._lyrics_busy = False
        self._combined_started_at = 0.0
        self._duration = 0.0
        self._comparison: OnlineLyricsComparisonPane | None = None
        self._setup_ui()

    def _setup_legacy_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        heading_row = QHBoxLayout()
        heading = QLabel("在线歌词与封面匹配")
        heading.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        self.transcribe_button = QPushButton("开始识别")
        self.transcribe_button.clicked.connect(lambda: self._request_action("transcribe_local"))
        heading_row.addWidget(self.transcribe_button)
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
        self.track_input.textChanged.connect(self._update_search_state)
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

        search_actions = QHBoxLayout()
        self.search_button = QPushButton("搜索歌词")
        self.search_button.clicked.connect(self._start_search)
        search_actions.addWidget(self.search_button)
        self.search_cover_button = QPushButton("搜索封面")
        self.search_cover_button.clicked.connect(self._start_cover_search)
        search_actions.addWidget(self.search_cover_button)
        self.local_cover_button = QPushButton("本地封面")
        self.local_cover_button.clicked.connect(self._choose_local_cover)
        search_actions.addWidget(self.local_cover_button)
        layout.addLayout(search_actions)

        self.result_stack = QStackedWidget()
        self.lyrics_results_page = QWidget()
        lyrics_results_layout = QVBoxLayout(self.lyrics_results_page)
        lyrics_results_layout.setContentsMargins(0, 0, 0, 0)
        self.cover_results_page = QWidget()
        cover_results_layout = QVBoxLayout(self.cover_results_page)
        cover_results_layout.setContentsMargins(0, 0, 0, 0)

        self.cover_list = QListWidget()
        self.cover_list.setViewMode(QListView.ViewMode.IconMode)
        self.cover_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.cover_list.setMovement(QListView.Movement.Static)
        self.cover_list.setWrapping(True)
        self.cover_list.setWordWrap(True)
        self.cover_list.setIconSize(QSize(110, 110))
        self.cover_list.setGridSize(QSize(150, 155))
        self.cover_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cover_list.itemClicked.connect(self._on_cover_item_clicked)
        cover_results_layout.addWidget(self.cover_list, 1)
        self.cover_status_label = QLabel("点击“搜索封面”后，候选图片会显示在这里。")
        self.cover_status_label.setWordWrap(True)
        self.cover_status_label.setStyleSheet("font-size:11px;color:#666")
        cover_results_layout.addWidget(self.cover_status_label)

        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["匹配", "歌名", "歌手", "时长", "同步"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.currentCellChanged.connect(self._on_result_selected)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        lyrics_results_layout.addWidget(self.results_table, 1)
        self.result_stack.addWidget(self.lyrics_results_page)
        self.result_stack.addWidget(self.cover_results_page)
        layout.addWidget(self.result_stack, 1)

        self.comparison_label = QLabel("选择搜索结果后，歌词会显示在左侧对照区的右半栏。")
        self.comparison_label.setWordWrap(True)
        self.comparison_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.comparison_label)

        self.lyrics_action_group = QGroupBox("识别、应用与校准")
        action_grid = QGridLayout(self.lyrics_action_group)
        self.use_local_button = QPushButton("直接应用左侧本地歌词")
        self.use_local_button.clicked.connect(lambda: self._request_action("use_local"))
        action_grid.addWidget(self.use_local_button, 0, 0)
        self.use_online_button = QPushButton("直接应用右侧在线歌词")
        self.use_online_button.clicked.connect(lambda: self._request_action("use_online"))
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
        self.calibrate_button.clicked.connect(lambda: self._request_action("calibrate"))
        action_grid.addWidget(self.calibrate_button, 2, 0, 1, 2)
        layout.addWidget(self.lyrics_action_group)

        self.status_label = QLabel("LRCLIB 只提供歌词，不提供歌曲音频。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.status_label)
        self._show_lyrics_results_mode()
        self._refresh_action_state()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.search_button = QPushButton("一键搜索歌词与封面")
        self.search_button.setObjectName("primaryAction")
        self.search_button.setMinimumWidth(190)
        self.search_button.setMinimumHeight(42)
        self.search_button.clicked.connect(self._start_combined_search)

        search_card = QGroupBox("歌曲与搜索条件")
        search_card.setObjectName("onlineSearchCard")
        self.search_card = search_card
        search_grid = QGridLayout(search_card)
        search_grid.setContentsMargins(12, 10, 12, 10)
        search_grid.setHorizontalSpacing(8)
        search_grid.setVerticalSpacing(7)
        self.source_filter = QComboBox()
        self.source_filter.addItem("全部素材", "all")
        self.source_filter.addItem("音乐库", "music")
        self.source_filter.addItem("视频库", "video")
        self.source_filter.currentIndexChanged.connect(self._rebuild_song_selector)
        self.song_selector = QComboBox()
        self.song_selector.setMinimumContentsLength(22)
        self.song_selector.currentIndexChanged.connect(self._on_song_selected)
        self.track_input = QLineEdit()
        self.track_input.textChanged.connect(self._update_search_state)
        self.artist_input = QLineEdit()
        self.album_input = QLineEdit()
        search_grid.addWidget(QLabel("来源"), 0, 0)
        search_grid.addWidget(self.source_filter, 0, 1)
        search_grid.addWidget(QLabel("素材"), 0, 2)
        search_grid.addWidget(self.song_selector, 0, 3, 1, 3)
        search_grid.addWidget(QLabel("歌名"), 1, 0)
        search_grid.addWidget(self.track_input, 1, 1)
        search_grid.addWidget(QLabel("歌手"), 1, 2)
        search_grid.addWidget(self.artist_input, 1, 3)
        search_grid.addWidget(QLabel("专辑"), 1, 4)
        search_grid.addWidget(self.album_input, 1, 5)
        search_grid.addWidget(
            self.search_button,
            0,
            6,
            2,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        search_grid.setColumnStretch(1, 2)
        search_grid.setColumnStretch(3, 3)
        search_grid.setColumnStretch(5, 2)
        self.current_file_label = QLabel("请先选择歌曲")
        self.current_file_label.setStyleSheet("font-size:11px;color:#667085")
        search_grid.addWidget(self.current_file_label, 2, 0, 1, 7)
        layout.addWidget(search_card)

        result_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.result_splitter = result_splitter
        result_splitter.setHandleWidth(8)
        lyrics_group = QGroupBox("在线歌词")
        lyrics_layout = QVBoxLayout(lyrics_group)
        lyrics_layout.setContentsMargins(10, 10, 10, 8)
        lyrics_layout.setSpacing(7)
        lyrics_content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.lyrics_content_splitter = lyrics_content_splitter
        lyrics_content_splitter.setChildrenCollapsible(False)
        lyrics_content_splitter.setHandleWidth(8)

        candidates_panel = QWidget()
        self.lyrics_candidates_panel = candidates_panel
        candidates_layout = QVBoxLayout(candidates_panel)
        candidates_layout.setContentsMargins(0, 0, 0, 0)
        candidates_layout.setSpacing(5)
        candidates_label = QLabel("候选结果")
        candidates_label.setStyleSheet("font-weight:600;color:#344054")
        candidates_layout.addWidget(candidates_label)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["匹配", "歌名", "歌手", "时长", "同步"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setMinimumHeight(245)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.currentCellChanged.connect(self._on_result_selected)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        candidates_layout.addWidget(self.results_table, 1)
        lyrics_content_splitter.addWidget(candidates_panel)

        self.online_result_pane = OnlineLyricsResultPane()
        self.online_result_pane.editor.setMinimumHeight(245)
        self.online_result_pane.content_changed.connect(self._online_result_edited)
        self.online_result_pane.playback_started.connect(self.playback_started)
        lyrics_content_splitter.addWidget(self.online_result_pane)
        lyrics_content_splitter.setStretchFactor(0, 4)
        lyrics_content_splitter.setStretchFactor(1, 6)
        lyrics_content_splitter.setSizes([380, 560])
        lyrics_layout.addWidget(lyrics_content_splitter, 1)

        self.online_player_group = self.online_result_pane.take_player_group()
        lyrics_layout.addWidget(self.online_player_group)
        self.lyrics_status_label = QLabel("点击一键搜索后，最佳匹配歌词会自动显示。")
        self.lyrics_status_label.setWordWrap(True)
        self.lyrics_status_label.setStyleSheet("font-size:11px;color:#667085")
        lyrics_layout.addWidget(self.lyrics_status_label)
        result_splitter.addWidget(lyrics_group)

        self.online_side_tabs = QTabWidget()
        self.online_side_tabs.setDocumentMode(True)
        self.online_side_tabs.setMinimumWidth(410)

        cover_page = QWidget()
        self.cover_page = cover_page
        cover_layout = QVBoxLayout(cover_page)
        cover_layout.setContentsMargins(10, 10, 10, 8)
        cover_layout.setSpacing(8)
        cover_actions = QHBoxLayout()
        self.search_cover_button = QPushButton("刷新封面")
        self.search_cover_button.clicked.connect(self._start_cover_search)
        cover_actions.addWidget(self.search_cover_button)
        self.local_cover_button = QPushButton("选择本地封面")
        self.local_cover_button.clicked.connect(self._choose_local_cover)
        cover_actions.addWidget(self.local_cover_button)
        cover_actions.addStretch()
        cover_layout.addLayout(cover_actions)
        self.cover_list = QListWidget()
        self.cover_list.setViewMode(QListView.ViewMode.IconMode)
        self.cover_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.cover_list.setMovement(QListView.Movement.Static)
        self.cover_list.setWrapping(True)
        self.cover_list.setWordWrap(True)
        self.cover_list.setIconSize(QSize(138, 138))
        self.cover_list.setGridSize(QSize(180, 190))
        self.cover_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cover_list.itemClicked.connect(self._on_cover_item_clicked)
        cover_layout.addWidget(self.cover_list, 1)
        self.cover_status_label = QLabel("一键搜索会同时查找 MusicBrainz 封面。")
        self.cover_status_label.setWordWrap(True)
        self.cover_status_label.setStyleSheet("font-size:11px;color:#667085")
        cover_layout.addWidget(self.cover_status_label)
        self.online_side_tabs.addTab(cover_page, "封面候选")

        tag_page = QWidget()
        self.tag_page = tag_page
        tag_layout = QVBoxLayout(tag_page)
        tag_layout.setContentsMargins(12, 12, 12, 10)
        tag_layout.setSpacing(10)
        tag_intro = QLabel("编辑当前音频的常用音乐信息")
        tag_intro.setStyleSheet("font-weight:700;color:#26354A")
        tag_layout.addWidget(tag_intro)
        tag_group = QGroupBox("音乐信息")
        tag_grid = QGridLayout(tag_group)
        tag_grid.setHorizontalSpacing(10)
        tag_grid.setVerticalSpacing(8)
        self.tag_fields: dict[str, QLineEdit] = {}
        for row, (key, label) in enumerate(
            (
                ("title", "标题"),
                ("artist", "歌手"),
                ("album", "专辑"),
                ("year", "年份"),
                ("track", "轨道号"),
            )
        ):
            field = QLineEdit()
            self.tag_fields[key] = field
            tag_grid.addWidget(QLabel(label), row, 0)
            tag_grid.addWidget(field, row, 1)
        tag_grid.setColumnStretch(1, 1)
        tag_layout.addWidget(tag_group)
        tag_layout.addStretch()
        self.tag_status_label = QLabel("保存只修改标签，不会重新编码音轨。")
        self.tag_status_label.setWordWrap(True)
        self.tag_status_label.setStyleSheet("font-size:11px;color:#667085")
        tag_layout.addWidget(self.tag_status_label)
        tag_actions = QHBoxLayout()
        self.fill_tags_button = QPushButton("用搜索信息填入")
        self.fill_tags_button.clicked.connect(self._fill_tags_from_search)
        tag_actions.addWidget(self.fill_tags_button)
        self.save_tags_button = QPushButton("保存音频标签")
        self.save_tags_button.setObjectName("primaryAction")
        self.save_tags_button.clicked.connect(self._request_tag_save)
        tag_actions.addWidget(self.save_tags_button)
        tag_layout.addLayout(tag_actions)
        self.online_side_tabs.addTab(tag_page, "音频标签")

        result_splitter.addWidget(self.online_side_tabs)
        result_splitter.setChildrenCollapsible(False)
        result_splitter.setStretchFactor(0, 7)
        result_splitter.setStretchFactor(1, 4)
        result_splitter.setSizes([900, 520])
        layout.addWidget(result_splitter, 1)

        self.status_label = QLabel("歌词与封面会并行搜索；最近结果会缓存 10 分钟。")
        self.status_label.setStyleSheet("font-size:11px;color:#667085")
        layout.addWidget(self.status_label)

        self.verification_panel = QWidget()
        verification_layout = QVBoxLayout(self.verification_panel)
        verification_layout.setContentsMargins(6, 6, 6, 6)
        verification_heading = QLabel("核对操作")
        verification_heading.setStyleSheet("font-weight:700;font-size:15px")
        verification_layout.addWidget(verification_heading)
        self.transcribe_button = QPushButton("开始本地识别")
        self.transcribe_button.clicked.connect(lambda: self._request_action("transcribe_local"))
        verification_layout.addWidget(self.transcribe_button)
        self.comparison_label = QLabel("先在在线页搜索歌词，再到这里核对。")
        self.comparison_label.setWordWrap(True)
        self.comparison_label.setStyleSheet("font-size:11px;color:#667085")
        verification_layout.addWidget(self.comparison_label)
        self.lyrics_action_group = QGroupBox("应用与校准")
        action_grid = QGridLayout(self.lyrics_action_group)
        self.use_local_button = QPushButton("采用左侧本地歌词")
        self.use_local_button.clicked.connect(lambda: self._request_action("use_local"))
        action_grid.addWidget(self.use_local_button, 0, 0)
        self.use_online_button = QPushButton("采用右侧在线歌词")
        self.use_online_button.clicked.connect(lambda: self._request_action("use_online"))
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
        self.calibrate_button = QPushButton("AI 核对并校准")
        self.calibrate_button.clicked.connect(lambda: self._request_action("calibrate"))
        action_grid.addWidget(self.calibrate_button, 2, 0, 1, 2)
        verification_layout.addWidget(self.lyrics_action_group)
        verification_layout.addStretch()
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
        if self.online_result_pane.content() != self._comparison.online_content():
            self.online_result_pane.set_content(self._comparison.online_content())
        self._refresh_action_state()
        if self._selected_match() is not None:
            self.refresh_local_comparison()

    def _online_result_edited(self):
        if self._comparison is not None:
            self._comparison.set_online_content(self.online_result_pane.content())
        self._refresh_action_state()

    def pause_playback(self):
        self.online_result_pane.pause_playback()

    def _local_content(self) -> str:
        return self._comparison.local_content() if self._comparison is not None else ""

    def _online_content(self) -> str:
        if self._comparison is not None:
            return self._comparison.online_content()
        return self.online_result_pane.content()

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
            (index for index, song in enumerate(visible_songs) if song.get("path") == current_path),
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
        self._cover_items.clear()
        self.cover_list.clear()
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
        self.online_result_pane.show_song(self._song)
        if self._comparison is not None:
            self._comparison.show_song(self._song)
        self.reload_cover()
        self.reload_tags()
        self.comparison_label.setText("在线页选中的歌词会显示在核对页右栏。")
        self.lyrics_status_label.setText("已选择本地素材，点击一键搜索在线歌词。")
        self.status_label.setText("已选择本地素材，可以并行搜索歌词与封面。")
        self._refresh_action_state()

    def _show_lyrics_results_mode(self):
        """Compatibility shim for older callers; both result types stay visible."""

    def _show_cover_results_mode(self):
        """Show the cover side tab while keeping lyrics visible."""
        self.online_side_tabs.setCurrentIndex(0)

    def reload_tags(self):
        media_path = self._song.get("path", "")
        values = {}
        if media_path and self._is_cover_editable_song():
            try:
                values = read_tags(str(media_path))
            except Exception as exc:
                self.tag_status_label.setText(f"无法读取音频标签：{exc}")
        for key, field in self.tag_fields.items():
            field.setText(str(values.get(key, "")))
        if media_path and self._is_cover_editable_song():
            self.tag_status_label.setText("已读取当前音频标签；保存不会重新编码音轨。")

    def _fill_tags_from_search(self):
        self.tag_fields["title"].setText(self.track_input.text().strip())
        self.tag_fields["artist"].setText(self.artist_input.text().strip())
        self.tag_fields["album"].setText(self.album_input.text().strip())
        self.tag_status_label.setText("已填入当前搜索信息，确认后点击保存音频标签。")

    def _request_tag_save(self):
        media_path = self._song.get("path", "")
        if not media_path or not self._is_cover_editable_song():
            self.tag_status_label.setText("当前素材格式不支持写入音频标签。")
            return
        values = {key: field.text().strip() for key, field in self.tag_fields.items()}
        self.action_requested.emit(
            str(media_path),
            TagApplyAction(values=values),
            "apply_tags",
        )

    def reload_cover(self):
        self._cover_matches = []
        self._cover_items.clear()
        self.cover_list.clear()
        media_path = self._song.get("path", "")
        if not media_path:
            self.cover_list.addItem("暂无内嵌封面")
            self._refresh_cover_state()
            return
        try:
            cover = read_cover_art(str(media_path))
        except Exception as exc:
            self.cover_list.addItem("无法读取内嵌封面")
            self.cover_status_label.setText(f"无法读取内嵌封面：{exc}")
            self._refresh_cover_state()
            return
        if cover:
            item = QListWidgetItem(self._cover_icon(cover[0]), "当前内嵌封面")
            item.setToolTip("当前音频文件中的封面")
            self.cover_list.addItem(item)
            self.cover_status_label.setText("当前封面已显示；搜索新封面后点击候选即可确认替换。")
        else:
            item = QListWidgetItem("暂无内嵌封面")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.cover_list.addItem(item)
            self.cover_status_label.setText(
                "点击“搜索封面”查看在线候选，或点击“本地封面”选择图片。"
            )
        self._refresh_cover_state()

    @staticmethod
    def _cover_icon(image_data: bytes) -> QIcon:
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_data):
            return QIcon()
        return QIcon(
            pixmap.scaled(
                110,
                110,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

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
        self.cover_list.setEnabled(editable and not self._cover_busy)
        self.fill_tags_button.setEnabled(editable)
        self.save_tags_button.setEnabled(editable)
        for field in self.tag_fields.values():
            field.setEnabled(editable)
        self._update_search_state()

    def _update_search_state(self):
        has_track = bool(self.track_input.text().strip())
        self.search_button.setEnabled(has_track and not self._lyrics_busy)

    def _start_cover_search(self):
        self.online_side_tabs.setCurrentIndex(0)
        if not self._is_cover_editable_song():
            self.cover_status_label.setText("当前素材格式不支持写入封面，请选择音乐文件。")
            return
        track_name = self.track_input.text().strip()
        album_name = self.album_input.text().strip()
        if not track_name and not album_name:
            self.cover_status_label.setText("请先填写歌名或专辑名。")
            return
        self._cover_busy = True
        self._cover_matches = []
        self._cover_items.clear()
        self.cover_list.clear()
        self._refresh_cover_state()
        self.cover_status_label.setText("正在快速搜索在线封面…")
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
        self._cover_items.clear()
        self.cover_list.clear()
        for match in self._cover_matches:
            date = f" · {match.first_release_date[:4]}" if match.first_release_date else ""
            artist = match.artist_name or "未知歌手"
            item = QListWidgetItem(f"{match.title}\n{artist}{date}\n匹配 {match.score:.0f}%")
            item.setData(Qt.ItemDataRole.UserRole, match)
            item.setToolTip("正在验证缩略图，载入后可点击")
            item.setFlags(
                item.flags()
                & ~Qt.ItemFlag.ItemIsEnabled
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            self.cover_list.addItem(item)
            self._cover_items[match.release_group_id] = item
        if self._cover_matches:
            self.cover_status_label.setText(
                f"找到 {len(self._cover_matches)} 张封面，正在载入缩略图…"
            )
            worker = CoverThumbnailWorker(self._cover_matches, self)
            self._cover_thumbnail_workers.append(worker)
            worker.thumbnail_ready.connect(self._cover_thumbnail_ready)
            worker.thumbnail_failed.connect(self._cover_thumbnail_failed)
            worker.finished.connect(
                lambda target=worker: self._cover_thumbnail_worker_finished(target)
            )
            worker.start()
        else:
            self.cover_status_label.setText("没有找到可用封面，可调整歌名/专辑名或选择本地图片。")
        self._refresh_cover_state()
        if not self._lyrics_busy:
            self.status_label.setText("搜索完成；歌词、封面和标签可在同一页处理。")

    def _cover_thumbnail_ready(
        self,
        _index: int,
        match: CoverArtMatch,
        image_data: bytes,
        _mime_type: str,
    ):
        item = self._cover_items.get(match.release_group_id)
        if item is not None:
            item.setIcon(self._cover_icon(image_data))
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setToolTip(f"来源：{match.source}；点击后下载大图并确认写入音频标签")

    def _cover_thumbnail_failed(self, match: CoverArtMatch):
        item = self._cover_items.pop(match.release_group_id, None)
        if item is None:
            return
        row = self.cover_list.row(item)
        if row >= 0:
            self.cover_list.takeItem(row)
        self._cover_matches = [
            candidate
            for candidate in self._cover_matches
            if candidate.release_group_id != match.release_group_id
        ]

    def _cover_thumbnail_worker_finished(self, worker: CoverThumbnailWorker):
        if worker in self._cover_thumbnail_workers:
            self._cover_thumbnail_workers.remove(worker)
        if self.cover_list.count():
            self.cover_status_label.setText(
                f"找到 {self.cover_list.count()} 张封面；点击一张即可确认使用。"
            )
        else:
            self.cover_status_label.setText(
                "候选均没有可用图片，可刷新重试或选择本地封面。"
            )

    def _show_cover_error(self, message: str):
        self._cover_busy = False
        self.cover_status_label.setText(f"封面搜索失败：{message}")
        self._refresh_cover_state()
        if not self._lyrics_busy:
            self.status_label.setText("搜索结束；封面搜索失败，歌词仍可继续使用。")

    def _on_cover_item_clicked(self, item: QListWidgetItem):
        match = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(match, CoverArtMatch):
            return
        self._cover_busy = True
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
        current_item = self.cover_list.currentItem()
        current = current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else None
        if not isinstance(current, CoverArtMatch):
            self._cover_busy = False
            self._refresh_cover_state()
            return
        if current.release_group_id != match.release_group_id:
            self._cover_busy = False
            self._refresh_cover_state()
            return
        self._cover_busy = False
        current_item.setIcon(self._cover_icon(image_data))
        self.cover_status_label.setText(f"已选择：{match.title}，请在确认框中决定是否写入。")
        self._emit_cover_apply(
            image_data,
            mime_type,
            f"在线封面：{match.title} · {match.artist_name or '未知歌手'}",
        )
        self._refresh_cover_state()

    def _choose_local_cover(self):
        self.online_side_tabs.setCurrentIndex(0)
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
        self._cover_matches = []
        self._cover_items.clear()
        self.cover_list.clear()
        item = QListWidgetItem(
            self._cover_icon(image_data),
            f"本地封面\n{Path(file_path).name}",
        )
        self.cover_list.addItem(item)
        self.cover_list.setCurrentItem(item)
        self.cover_status_label.setText(f"已选择本地封面：{Path(file_path).name}，等待确认。")
        self._emit_cover_apply(
            image_data,
            mime_type,
            f"本地封面：{Path(file_path).name}",
        )

    def _emit_cover_apply(
        self,
        image_data: bytes,
        mime_type: str,
        source: str,
    ):
        media_path = self._song.get("path")
        if not media_path:
            return
        self.action_requested.emit(
            str(media_path),
            CoverApplyAction(
                image_data=image_data,
                mime_type=image_mime_type(image_data, mime_type),
                source=source,
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

    def _start_combined_search(self):
        if not self.track_input.text().strip():
            self.status_label.setText("请先选择歌曲或填写搜索歌名。")
            return
        self.online_side_tabs.setCurrentIndex(0)
        self._combined_started_at = monotonic()
        self.status_label.setText("正在并行搜索歌词与封面…")
        self._start_search()
        if self._is_cover_editable_song():
            self._start_cover_search()

    def _start_search(self):
        track_name = self.track_input.text().strip()
        if not track_name:
            self.status_label.setText("请先选择歌曲或填写搜索歌名。")
            return
        self._lyrics_busy = True
        self._update_search_state()
        self.lyrics_status_label.setText("正在搜索 LRCLIB…")
        self._search_worker = LRCLIBSearchWorker(
            track_name,
            self.artist_input.text().strip(),
            self.album_input.text().strip(),
            self._duration,
            self,
        )
        self._search_worker.quick_result.connect(self._show_quick_result)
        self._search_worker.completed.connect(self._show_results)
        self._search_worker.failed.connect(self._show_search_error)
        self._search_worker.start()

    def _populate_lyrics_results(self, matches: list):
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

    def _show_quick_result(self, matches: list):
        if not matches:
            return
        self._populate_lyrics_results(matches)
        elapsed = monotonic() - self._combined_started_at if self._combined_started_at else 0
        suffix = f"，用时 {elapsed:.1f} 秒" if elapsed else ""
        self.lyrics_status_label.setText(
            f"精确匹配已显示{suffix}；更多候选仍在后台补充。"
        )
        self.status_label.setText("歌词已先显示，封面和更多候选仍在后台加载。")
        self._refresh_action_state()

    def _show_results(self, matches: list):
        self._lyrics_busy = False
        self._populate_lyrics_results(matches)
        if self._matches:
            elapsed = monotonic() - self._combined_started_at if self._combined_started_at else 0
            suffix = f"，用时 {elapsed:.1f} 秒" if elapsed else ""
            self.lyrics_status_label.setText(
                f"找到 {len(self._matches)} 条结果{suffix}；已自动显示最佳匹配。"
            )
        else:
            if self._comparison is not None:
                self._comparison.set_online_content("")
            self.online_result_pane.set_content("")
            self.lyrics_status_label.setText("没有找到匹配结果，请调整歌名或歌手。")
        if not self._cover_busy:
            self.status_label.setText("搜索完成；歌词、封面和标签可在同一页处理。")
        else:
            self.status_label.setText("歌词已就绪，封面仍在后台加载。")
        self._refresh_action_state()

    def _show_search_error(self, message: str):
        self._lyrics_busy = False
        self.lyrics_status_label.setText(f"歌词搜索失败：{message}")
        if not self._cover_busy:
            self.status_label.setText("搜索结束；歌词搜索失败，可检查网络后重试。")
        self._update_search_state()

    def _selected_match(self) -> LyricsMatch | None:
        row = self.results_table.currentRow()
        return self._matches[row] if 0 <= row < len(self._matches) else None

    def _on_result_selected(self, *_args):
        match = self._selected_match()
        if match is None:
            if self._comparison is not None:
                self._comparison.set_online_content("")
            self.online_result_pane.set_content("")
            self._refresh_action_state()
            return
        content = simplify_lyrics_content(match.synced_lyrics or match.plain_lyrics)
        self.online_result_pane.set_content(content)
        if self._comparison is not None:
            self._comparison.set_online_content(content)
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
        self.transcribe_button.setText("重新本地识别" if has_local_timeline else "开始本地识别")
        self.transcribe_button.setEnabled(has_song)
        self.use_local_button.setEnabled(has_local_timeline)
        self.use_online_button.setEnabled(has_online_timeline)
        self.merge_local_button.setEnabled(has_local_timeline and has_online_text)
        self.merge_online_button.setEnabled(has_online_timeline and bool(local_content.strip()))
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
