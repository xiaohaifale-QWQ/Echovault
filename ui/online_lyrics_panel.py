"""Five-workspace online lyric comparison, editing, merging, and playback UI."""

from dataclasses import dataclass, replace
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextFormat
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.online_lyrics import (
    LyricsMatch,
    active_lrc_line_index,
    calibrate_lrc_with_reference,
    compare_lyrics,
    media_search_metadata,
    search_lrclib,
    timed_text_entries,
)


@dataclass(frozen=True)
class OnlineLyricsAction:
    """All content needed to safely apply one comparison choice."""

    match: LyricsMatch
    local_content: str
    online_content: str


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


class LyricsCalibrationWorker(QThread):
    completed = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, lrc_path, match, ai_settings, parent=None):
        super().__init__(parent)
        self.lrc_path = lrc_path
        self.match = match
        self.ai_settings = ai_settings

    def run(self):
        reference = self.match.synced_lyrics or self.match.plain_lyrics
        try:
            output, backup = calibrate_lrc_with_reference(
                self.lrc_path,
                reference,
                ai_settings=self.ai_settings,
                track_name=self.match.track_name,
                artist_name=self.match.artist_name,
            )
            self.completed.emit(str(output), str(backup))
        except Exception as exc:
            self.failed.emit(str(exc))


class LyricsCompareEditor(QPlainTextEdit):
    """Read-only comparison view that enters edit mode on double click."""

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


class OnlineLyricsPanel(QWidget):
    action_requested = pyqtSignal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs: list[dict] = []
        self._song: dict = {}
        self._matches: list[LyricsMatch] = []
        self._duration = 0.0
        self._seeking = False
        self._setup_ui()
        self._setup_player()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        heading_row = QHBoxLayout()
        heading = QLabel("在线歌词匹配与双轨核对")
        heading.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        self.search_button = QPushButton("搜索 LRCLIB")
        self.search_button.clicked.connect(self._start_search)
        heading_row.addWidget(self.search_button)
        layout.addLayout(heading_row)

        form = QFormLayout()
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
        self.candidate_selector = QComboBox()
        self.candidate_selector.setEnabled(False)
        self.candidate_selector.currentIndexChanged.connect(self._on_candidate_selected)
        form.addRow("在线候选:", self.candidate_selector)
        layout.addLayout(form)

        self.current_file_label = QLabel("请从下拉框选择一个素材")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.current_file_label)

        self.comparison_label = QLabel("左侧显示本软件歌词，右侧显示在线候选歌词")
        self.comparison_label.setWordWrap(True)
        self.comparison_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.comparison_label)

        comparison_splitter = QSplitter(Qt.Orientation.Horizontal)
        local_group = QGroupBox("左：本软件识别歌词（双击修改）")
        local_layout = QVBoxLayout(local_group)
        self.local_editor = LyricsCompareEditor()
        self.local_editor.setReadOnly(True)
        self.local_editor.setPlaceholderText("尚无本地识别歌词")
        self.local_editor.edit_requested.connect(self._begin_editing)
        local_layout.addWidget(self.local_editor)
        comparison_splitter.addWidget(local_group)

        online_group = QGroupBox("右：在线匹配歌词（双击修改）")
        online_layout = QVBoxLayout(online_group)
        self.online_editor = LyricsCompareEditor()
        self.online_editor.setReadOnly(True)
        self.online_editor.setPlaceholderText("搜索并选择在线候选后显示歌词")
        self.online_editor.edit_requested.connect(self._begin_editing)
        online_layout.addWidget(self.online_editor)
        comparison_splitter.addWidget(online_group)
        comparison_splitter.setSizes([1, 1])
        layout.addWidget(comparison_splitter, 3)

        action_grid = QGridLayout()
        self.use_local_button = QPushButton("采用左侧本地歌词")
        self.use_local_button.clicked.connect(lambda: self._request_action("use_local"))
        action_grid.addWidget(self.use_local_button, 0, 0)
        self.use_online_button = QPushButton("采用右侧在线歌词")
        self.use_online_button.clicked.connect(lambda: self._request_action("use_online"))
        action_grid.addWidget(self.use_online_button, 0, 1)
        self.merge_local_button = QPushButton("合并：左时间轴 + 右文字")
        self.merge_local_button.clicked.connect(
            lambda: self._request_action("merge_local_timeline")
        )
        action_grid.addWidget(self.merge_local_button, 1, 0)
        self.merge_online_button = QPushButton("合并：右时间轴 + 左文字")
        self.merge_online_button.clicked.connect(
            lambda: self._request_action("merge_online_timeline")
        )
        action_grid.addWidget(self.merge_online_button, 1, 1)
        self.calibrate_button = QPushButton("AI 核对并校准左侧文字")
        self.calibrate_button.clicked.connect(lambda: self._request_action("calibrate"))
        action_grid.addWidget(self.calibrate_button, 2, 0, 1, 2)
        layout.addLayout(action_grid)

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

        self.status_label = QLabel("LRCLIB 只提供歌词；播放器使用当前本地素材。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.status_label)
        self._refresh_action_state()

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

    def set_songs(self, songs: list[dict]):
        """Populate the song drop-down without discarding the current selection."""
        current_path = self._song.get("path", "")
        self._songs = [dict(song) for song in songs if song.get("path")]
        self.song_selector.blockSignals(True)
        self.song_selector.clear()
        for song in self._songs:
            name = Path(song.get("name") or song["path"]).stem
            self.song_selector.addItem(name, song)
        selected_index = next(
            (index for index, song in enumerate(self._songs) if song.get("path") == current_path),
            -1,
        )
        self.song_selector.setCurrentIndex(selected_index)
        self.song_selector.blockSignals(False)

    def _on_song_selected(self, index: int):
        if 0 <= index < len(self._songs):
            self.show_song(self._songs[index], sync_selector=False)

    def show_song(self, song: dict, *, sync_selector: bool = True):
        if not song or not song.get("path"):
            return
        self.player.stop()
        self._song = dict(song)
        path = Path(song["path"])
        self._song["lrc_path"] = str(path.with_suffix(".lrc"))
        self._song["has_lrc"] = path.with_suffix(".lrc").is_file()
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
        self.reload_local_lyrics()
        self._matches = []
        self.candidate_selector.blockSignals(True)
        self.candidate_selector.clear()
        self.candidate_selector.blockSignals(False)
        self.candidate_selector.setEnabled(False)
        self.online_editor.clear()
        self.online_editor.setReadOnly(True)
        self.comparison_label.setText("搜索后从在线候选下拉框选择一份歌词进行核对")
        self.status_label.setText("已选择本地素材，可以搜索公开歌词库。")
        if path.is_file():
            self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self.play_button.setEnabled(True)
        else:
            self.player.setSource(QUrl())
            self.play_button.setEnabled(False)
        self._refresh_action_state()

    def reload_local_lyrics(self):
        lrc_path = Path(self._song.get("lrc_path", ""))
        try:
            content = lrc_path.read_text(encoding="utf-8") if lrc_path.is_file() else ""
        except (OSError, UnicodeError) as exc:
            content = ""
            self.status_label.setText(f"无法读取本地歌词：{exc}")
        self.local_editor.setPlainText(content)
        self.local_editor.setReadOnly(True)
        self._refresh_action_state()

    @staticmethod
    def _format_duration(duration: float) -> str:
        minutes, seconds = divmod(int(round(duration)), 60)
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _format_milliseconds(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

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
        self.candidate_selector.blockSignals(True)
        self.candidate_selector.clear()
        for match in self._matches:
            timeline = "同步" if match.has_synced_lyrics else "纯文本"
            self.candidate_selector.addItem(
                f"{match.score:.0f}% · {match.track_name} · "
                f"{match.artist_name or '未知歌手'} · {timeline}"
            )
        self.candidate_selector.blockSignals(False)
        self.candidate_selector.setEnabled(bool(self._matches))
        if self._matches:
            self.candidate_selector.setCurrentIndex(0)
            self._on_candidate_selected(0)
            self.status_label.setText(f"找到 {len(self._matches)} 条结果，可展开候选框切换。")
        else:
            self.online_editor.clear()
            self.status_label.setText("没有找到匹配结果，请调整歌名或歌手。")
        self._refresh_action_state()

    def _show_search_error(self, message: str):
        self.search_button.setEnabled(True)
        self.status_label.setText(f"搜索失败：{message}")

    def _selected_match(self) -> LyricsMatch | None:
        index = self.candidate_selector.currentIndex()
        return self._matches[index] if 0 <= index < len(self._matches) else None

    def _on_candidate_selected(self, index: int):
        if not 0 <= index < len(self._matches):
            self.online_editor.clear()
            self._refresh_action_state()
            return
        match = self._matches[index]
        self.online_editor.setPlainText(match.synced_lyrics or match.plain_lyrics)
        self.online_editor.setReadOnly(True)
        self.refresh_local_comparison()
        self._refresh_action_state()

    def refresh_local_comparison(self):
        match = self._selected_match()
        if match is None:
            return
        local_content = self.local_editor.toPlainText()
        online_content = self.online_editor.toPlainText()
        if not timed_text_entries(local_content):
            self.comparison_label.setText(
                "左侧暂无同步 LRC；可采用右侧同步歌词，或先完成本地识别。"
            )
            return
        comparison = compare_lyrics(local_content, online_content)
        self.comparison_label.setText(
            f"文字相似度 {comparison['similarity'] * 100:.1f}% · "
            f"左 {comparison['local_lines']} 行 / 右 {comparison['reference_lines']} 行 · "
            "播放时两侧按各自时间轴同步高亮"
        )

    def _begin_editing(self, editor: LyricsCompareEditor):
        self.player.pause()
        editor.setReadOnly(False)
        editor.setFocus()
        side = "左侧本地" if editor is self.local_editor else "右侧在线"
        self.status_label.setText(f"已暂停并进入{side}编辑；采用或合并时会使用当前内容。")

    def _refresh_action_state(self):
        local_content = self.local_editor.toPlainText() if hasattr(self, "local_editor") else ""
        online_content = self.online_editor.toPlainText() if hasattr(self, "online_editor") else ""
        has_local_timeline = bool(timed_text_entries(local_content))
        has_online_timeline = bool(timed_text_entries(online_content))
        has_online_text = bool(online_content.strip())
        self.use_local_button.setEnabled(has_local_timeline)
        self.use_online_button.setEnabled(has_online_timeline)
        self.merge_local_button.setEnabled(has_local_timeline and has_online_text)
        self.merge_online_button.setEnabled(has_online_timeline and bool(local_content.strip()))
        self.calibrate_button.setEnabled(has_local_timeline and has_online_text)

    def _request_action(self, action: str):
        match = self._selected_match()
        media_path = self._song.get("path")
        if match is None or not media_path:
            return
        online_content = self.online_editor.toPlainText()
        if timed_text_entries(online_content):
            edited_match = replace(match, synced_lyrics=online_content)
        else:
            edited_match = replace(match, synced_lyrics="", plain_lyrics=online_content)
        payload = OnlineLyricsAction(
            match=edited_match,
            local_content=self.local_editor.toPlainText(),
            online_content=online_content,
        )
        self.action_requested.emit(str(media_path), payload, action)

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.local_editor.setReadOnly(True)
            self.online_editor.setReadOnly(True)
            self.player.play()

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

    def _on_position_changed(self, position: int):
        if not self._seeking:
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(position)
            self.position_slider.blockSignals(False)
        self.time_label.setText(
            f"{self._format_milliseconds(position)} / "
            f"{self._format_milliseconds(self.player.duration())}"
        )
        seconds = position / 1000.0
        self.local_editor.highlight_at(seconds)
        self.online_editor.highlight_at(seconds)

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
        seconds = position / 1000.0
        self.local_editor.highlight_at(seconds)
        self.online_editor.highlight_at(seconds)
