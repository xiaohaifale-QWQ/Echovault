"""Original desktop audio-download workspace for authorized catalogs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QStyle,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.audio_sources import (
    download_audio,
    resolve_download,
    search_source,
    suggested_filename,
)
from ui.playback_coordinator import PlaybackSession
from ui.system_audio import apply_system_default_audio


class AudioSourceSearchWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, source: dict, query: str, parent=None):
        super().__init__(parent)
        self.source = dict(source)
        self.query = query

    def run(self):
        try:
            self.completed.emit(search_source(self.source, self.query))
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))


class AudioDownloadWorker(QThread):
    progress_changed = pyqtSignal(int)
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        source: dict,
        track: dict,
        quality: str,
        output_path: str,
        parent=None,
    ):
        super().__init__(parent)
        self.source = dict(source)
        self.track = dict(track)
        self.quality = quality
        self.output_path = output_path

    def run(self):
        try:
            url, headers = resolve_download(
                self.source,
                self.track,
                self.quality,
            )
            result = download_audio(
                url,
                headers,
                self.output_path,
                self.progress_changed.emit,
                allow_remote_http=self.source.get("type") == "lx_js",
            )
            self.completed.emit(result)
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))


class AudioPreviewResolveWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(object)
    MAX_RESULTS_PER_SOURCE = 4
    MAX_TOTAL_ATTEMPTS = 12

    def __init__(
        self,
        token: int,
        sources: list[dict],
        source_index: int,
        tracks: list[dict],
        track_index: int,
        query: str,
        parent=None,
    ):
        super().__init__(parent)
        self.token = token
        self.sources = [dict(source) for source in sources]
        self.source_index = source_index
        self.tracks = [dict(track) for track in tracks]
        self.track_index = track_index
        self.query = query.strip()

    @staticmethod
    def _quality(source: dict, track: dict) -> str:
        supported = set(source.get("qualities", []))
        qualities = [
            quality
            for quality in track.get("qualities", [])
            if quality in supported
        ]
        if not qualities:
            qualities = list(source.get("qualities", []))
        return "128k" if "128k" in qualities else (qualities[0] if qualities else "")

    def _source_tracks(self, index: int, source: dict) -> list[dict]:
        if index == self.source_index:
            return list(self.tracks)
        if not self.query:
            return []
        return search_source(source, self.query)

    def run(self):
        if not self.sources or not 0 <= self.source_index < len(self.sources):
            self.failed.emit(
                {"token": self.token, "message": "当前没有可用音源。"}
            )
            return

        source_order = [
            self.source_index,
            *(
                index
                for index in range(len(self.sources))
                if index != self.source_index
            ),
        ]
        attempts = 0
        errors: list[str] = []
        for source_index in source_order:
            source = self.sources[source_index]
            try:
                tracks = self._source_tracks(source_index, source)
            except (OSError, ValueError) as exc:
                errors.append(f"{source.get('name', '未命名音源')}: {exc}")
                continue
            if not tracks:
                errors.append(f"{source.get('name', '未命名音源')}: 没有搜索结果")
                continue

            start_index = self.track_index if source_index == self.source_index else 0
            indexes = [
                start_index,
                *(
                    index
                    for index in range(len(tracks))
                    if index != start_index
                ),
            ][: self.MAX_RESULTS_PER_SOURCE]
            for track_index in indexes:
                if attempts >= self.MAX_TOTAL_ATTEMPTS:
                    break
                track = tracks[track_index]
                quality = self._quality(source, track)
                if not quality:
                    errors.append(
                        f"{source.get('name', '未命名音源')}: "
                        f"{track.get('title', '未命名歌曲')} 没有可用音质"
                    )
                    continue
                attempts += 1
                try:
                    url, headers = resolve_download(source, track, quality)
                except (OSError, ValueError) as exc:
                    errors.append(
                        f"{source.get('name', '未命名音源')}: "
                        f"{track.get('title', '未命名歌曲')} - {exc}"
                    )
                    continue
                self.completed.emit(
                    {
                        "token": self.token,
                        "url": url,
                        "headers": headers,
                        "source": source,
                        "source_index": source_index,
                        "tracks": tracks,
                        "track": track,
                        "track_index": track_index,
                        "quality": quality,
                        "attempts": attempts,
                    }
                )
                return
            if attempts >= self.MAX_TOTAL_ATTEMPTS:
                break

        summary = errors[-1] if errors else "没有找到可播放地址。"
        self.failed.emit(
            {
                "token": self.token,
                "message": f"已自动尝试 {attempts} 个候选，仍无法试听。{summary}",
                "attempts": attempts,
            }
        )


class AudioDownloadPanel(QWidget):
    """Search, inspect and download from user-configured authorized sources."""

    download_completed = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._sources: list[dict] = []
        self._tracks: list[dict] = []
        self._display_tracks: list[dict] = []
        self._download_history: list[dict] = []
        self._download_target: dict | None = None
        self._download_source: dict | None = None
        self._search_worker: AudioSourceSearchWorker | None = None
        self._download_worker: AudioDownloadWorker | None = None
        self._preview_worker: AudioPreviewResolveWorker | None = None
        self._preview_token = 0
        self._preview_track_id = ""
        self._preview_track: dict | None = None
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        apply_system_default_audio(self._audio_output)
        self._playback_session = PlaybackSession(self._player)
        self._setup_ui()
        self._player.positionChanged.connect(self._preview_position_changed)
        self._player.durationChanged.connect(self._preview_duration_changed)
        self._player.playbackStateChanged.connect(self._preview_state_changed)
        self._player.mediaStatusChanged.connect(self._preview_media_status_changed)
        self._player.errorOccurred.connect(self._preview_player_error)
        self.reload_config(config)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("downloadTopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 8)
        top_layout.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("downloadSearchEdit")
        self.search_edit.setPlaceholderText("搜索歌曲、歌手或专辑…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(430)
        self.search_edit.returnPressed.connect(self._start_search)
        top_layout.addWidget(self.search_edit)
        self.search_button = QPushButton("搜索")
        self.search_button.setObjectName("downloadSearchButton")
        self.search_button.clicked.connect(self._start_search)
        top_layout.addWidget(self.search_button)
        top_layout.addStretch()
        self.content_tabs = QTabBar()
        self.content_tabs.setObjectName("downloadContentTabs")
        self.content_tabs.setDrawBase(False)
        self.content_tabs.addTab("歌曲")
        self.content_tabs.addTab("下载记录")
        self.content_tabs.currentChanged.connect(self._content_tab_changed)
        top_layout.addWidget(self.content_tabs)
        layout.addWidget(top_bar)

        source_row = QFrame()
        source_row.setObjectName("downloadSourceRow")
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 5)
        self.source_tabs = QTabBar()
        self.source_tabs.setObjectName("downloadSourceTabs")
        self.source_tabs.setDrawBase(False)
        self.source_tabs.setExpanding(False)
        self.source_tabs.currentChanged.connect(self._source_tab_changed)
        source_layout.addWidget(self.source_tabs)
        source_layout.addStretch()
        self.result_count_label = QLabel("")
        self.result_count_label.setObjectName("downloadResultCount")
        source_layout.addWidget(self.result_count_label)
        layout.addWidget(source_row)

        self.results_table = QTableWidget(0, 6)
        self.results_table.setObjectName("downloadResultsTable")
        self.results_table.setHorizontalHeaderLabels(
            ["#", "歌曲名", "艺术家", "专辑名", "时长", "音质"]
        )
        self.results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.results_table.verticalHeader().hide()
        self.results_table.setShowGrid(False)
        self.results_table.setAlternatingRowColors(False)
        self.results_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.results_table.verticalHeader().setDefaultSectionSize(45)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.results_table.setColumnWidth(0, 46)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.itemSelectionChanged.connect(self._show_selection)
        self.results_table.doubleClicked.connect(self._toggle_preview)
        layout.addWidget(self.results_table, 1)

        self.preview_bar = QFrame()
        self.preview_bar.setObjectName("downloadPreviewBar")
        player_layout = QHBoxLayout(self.preview_bar)
        player_layout.setContentsMargins(14, 9, 14, 9)
        player_layout.setSpacing(10)

        self.preview_cover = QLabel("♪")
        self.preview_cover.setObjectName("downloadPreviewCover")
        self.preview_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_cover.setFixedSize(50, 50)
        player_layout.addWidget(self.preview_cover)

        song_copy = QVBoxLayout()
        song_copy.setSpacing(2)
        self.preview_title = QLabel("选择一首歌曲")
        self.preview_title.setObjectName("downloadPreviewTitle")
        self.preview_title.setMinimumWidth(180)
        self.preview_artist = QLabel("双击歌曲或点击播放开始试听")
        self.preview_artist.setObjectName("downloadPreviewArtist")
        song_copy.addWidget(self.preview_title)
        song_copy.addWidget(self.preview_artist)
        player_layout.addLayout(song_copy)

        self.preview_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_slider.setObjectName("downloadPreviewSlider")
        self.preview_slider.setRange(0, 0)
        self.preview_slider.sliderMoved.connect(self._seek_preview)
        self.preview_slider.sliderReleased.connect(
            lambda: self._seek_preview(self.preview_slider.value())
        )
        player_layout.addWidget(self.preview_slider, 1)

        self.preview_time = QLabel("00:00 / 00:00")
        self.preview_time.setObjectName("downloadPreviewTime")
        self.preview_time.setMinimumWidth(105)
        player_layout.addWidget(self.preview_time)

        self.previous_button = QPushButton()
        self.previous_button.setObjectName("downloadTransportButton")
        self.previous_button.setToolTip("上一首")
        self.previous_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward)
        )
        self.previous_button.clicked.connect(lambda: self._play_adjacent(-1))
        player_layout.addWidget(self.previous_button)

        self.preview_play_button = QPushButton()
        self.preview_play_button.setObjectName("downloadMainPlayButton")
        self.preview_play_button.setToolTip("播放")
        self.preview_play_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.preview_play_button.clicked.connect(self._toggle_preview)
        player_layout.addWidget(self.preview_play_button)

        self.next_button = QPushButton()
        self.next_button.setObjectName("downloadTransportButton")
        self.next_button.setToolTip("下一首")
        self.next_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward)
        )
        self.next_button.clicked.connect(lambda: self._play_adjacent(1))
        player_layout.addWidget(self.next_button)

        self.stage_download_button = QPushButton("下载此歌曲")
        self.stage_download_button.setObjectName("downloadStageButton")
        self.stage_download_button.setEnabled(False)
        self.stage_download_button.clicked.connect(self._open_download_record)
        player_layout.addWidget(self.stage_download_button)
        layout.addWidget(self.preview_bar)

        self.action_bar = QFrame()
        self.action_bar.setObjectName("downloadActionBar")
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(12, 9, 12, 9)
        action_layout.setSpacing(8)
        self.track_title = QLabel("选择一首歌曲")
        self.track_title.setObjectName("downloadSelectedTitle")
        self.track_title.setMinimumWidth(180)
        action_layout.addWidget(self.track_title)
        action_layout.addWidget(QLabel("音质"))
        self.quality_combo = QComboBox()
        self.quality_combo.setMinimumWidth(150)
        action_layout.addWidget(self.quality_combo)
        action_layout.addWidget(QLabel("保存到"))
        self.directory_edit = QLineEdit()
        action_layout.addWidget(self.directory_edit, 1)
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._browse_directory)
        action_layout.addWidget(browse_button)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(130)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        action_layout.addWidget(self.progress)
        self.download_button = QPushButton("下载")
        self.download_button.setObjectName("primaryAction")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._start_download)
        action_layout.addWidget(self.download_button)
        layout.addWidget(self.action_bar)
        self.action_bar.hide()

        self.status_label = QLabel("请先在设置中添加并启用授权音源。")
        self.status_label.setObjectName("downloadStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#downloadTopBar, QFrame#downloadSourceRow {
                background:transparent; border:none;
            }
            QLineEdit#downloadSearchEdit {
                background:#E9EDF2; border:none; border-radius:5px;
                min-height:36px; padding:0 12px; font-size:14px;
            }
            QPushButton#downloadSearchButton {
                min-width:58px; min-height:36px; border:none;
                background:#E9EDF2; border-radius:5px; color:#506074;
            }
            QTabBar#downloadSourceTabs::tab,
            QTabBar#downloadContentTabs::tab {
                background:transparent; border:none; color:#526173;
                padding:9px 14px; min-width:42px;
            }
            QTabBar#downloadSourceTabs::tab:selected,
            QTabBar#downloadContentTabs::tab:selected {
                color:#1F6FBB; font-weight:700;
                border-bottom:2px solid #7EA6CC;
            }
            QTableWidget#downloadResultsTable {
                background:#FFFFFF; border:none; border-top:1px solid #E6EBF1;
                selection-background-color:#EDF5FE; selection-color:#17233A;
                alternate-background-color:#FFFFFF;
            }
            QTableWidget#downloadResultsTable::item {
                border:none; border-bottom:1px solid #F0F3F6; padding:5px 8px;
            }
            QHeaderView::section {
                background:#FFFFFF; border:none; border-bottom:1px solid #E2E7ED;
                color:#4B5563; padding:8px; font-weight:600;
            }
            QFrame#downloadActionBar, QFrame#downloadPreviewBar {
                background:#F7F9FC; border-top:1px solid #E1E7EE;
                border-bottom:1px solid #E1E7EE;
            }
            QLabel#downloadPreviewCover {
                background:#E4EDF7; color:#4A82B8; border-radius:6px;
                font-size:24px; font-weight:700;
            }
            QLabel#downloadPreviewTitle {
                color:#17233A; font-weight:700; font-size:14px;
            }
            QLabel#downloadPreviewArtist, QLabel#downloadPreviewTime {
                color:#7B8796; font-size:11px;
            }
            QPushButton#downloadTransportButton {
                min-width:34px; max-width:34px; min-height:34px; max-height:34px;
                padding:0; border:none; border-radius:17px; background:transparent;
            }
            QPushButton#downloadTransportButton:hover {
                background:#E5EDF6;
            }
            QPushButton#downloadMainPlayButton {
                min-width:42px; max-width:42px; min-height:42px; max-height:42px;
                padding:0; border:none; border-radius:21px;
                background:#DCE9F7;
            }
            QPushButton#downloadMainPlayButton:hover { background:#C8DDF2; }
            QPushButton#downloadStageButton {
                min-height:34px; padding:0 12px; border:1px solid #CAD7E5;
                border-radius:6px; background:#FFFFFF; color:#33506E;
            }
            QSlider#downloadPreviewSlider { min-height:22px; }
            QLabel#downloadSelectedTitle {
                color:#1F2937; font-weight:700;
            }
            QLabel#downloadResultCount, QLabel#downloadStatus {
                color:#7B8796; font-size:11px;
            }
            """
        )

    def reload_config(self, config):
        self.config = config
        self._sources = [
            dict(source)
            for source in getattr(config, "audio_sources", [])
            if source.get("enabled", True)
        ]
        current_index = self.source_tabs.currentIndex()
        while self.source_tabs.count():
            self.source_tabs.removeTab(0)
        for source in self._sources:
            self.source_tabs.addTab(source.get("name", "未命名音源"))
        if self._sources:
            self.source_tabs.setCurrentIndex(
                max(0, min(current_index, len(self._sources) - 1))
            )
        else:
            self.source_tabs.addTab("未配置音源")
            self.source_tabs.setTabEnabled(0, False)
        default_dir = getattr(config, "audio_download_dir", "")
        if not default_dir:
            music_dirs = getattr(config, "music_dirs", [])
            default_dir = (
                music_dirs[0]
                if music_dirs
                else str(Path.home() / "Music" / "Echovault下载")
            )
        self.directory_edit.setText(default_dir)
        has_sources = bool(self._sources)
        self.search_button.setEnabled(has_sources)
        self.search_edit.setEnabled(has_sources)
        self.status_label.setText(
            "输入关键词后搜索；下载文件会自动加入素材库。"
            if has_sources
            else "没有可用音源，请到“设置 → 音源管理”添加授权音源。"
        )

    def _current_source(self) -> dict | None:
        index = self.source_tabs.currentIndex()
        return self._sources[index] if 0 <= index < len(self._sources) else None

    def _source_tab_changed(self, _index: int):
        self._preview_token += 1
        self.preview_play_button.setEnabled(True)
        self._player.stop()
        self._preview_track = None
        self._preview_track_id = ""
        self._tracks = []
        if hasattr(self, "results_table"):
            self._render_tracks([])
        source = self._current_source()
        if source is not None:
            self.status_label.setText(f"当前音源：{source['name']}。输入关键词开始搜索。")

    def _content_tab_changed(self, index: int):
        if index == 0:
            self._render_tracks(self._tracks)
            self.search_edit.setEnabled(bool(self._sources))
            self.search_button.setEnabled(bool(self._sources))
            self.preview_bar.show()
            self.action_bar.hide()
        else:
            self._player.pause()
            self._render_tracks(self._download_history)
            self.search_edit.setEnabled(False)
            self.search_button.setEnabled(False)
            self.preview_bar.hide()
            self.action_bar.show()
        self.download_button.setEnabled(
            index == 1
            and self._download_target is not None
            and bool(self.quality_combo.currentData())
        )

    def _render_tracks(self, tracks: list[dict]):
        self._display_tracks = list(tracks)
        self.results_table.clearSelection()
        self.results_table.setRowCount(len(self._display_tracks))
        for row, track in enumerate(self._display_tracks):
            values = (
                str(row + 1),
                track.get("title", ""),
                track.get("artist", ""),
                track.get("album", ""),
                track.get("duration", ""),
                " / ".join(track.get("qualities", [])),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.results_table.setItem(row, column, item)
        label = "首搜索结果" if self.content_tabs.currentIndex() == 0 else "条下载记录"
        self.result_count_label.setText(
            f"{len(self._display_tracks)} {label}" if self._display_tracks else ""
        )
        if self._display_tracks:
            self.results_table.selectRow(0)

    def _start_search(self):
        source = self._current_source()
        query = self.search_edit.text().strip()
        if source is None:
            QMessageBox.information(self, "音频下载", "请先在设置中添加音源。")
            return
        if not query:
            return
        self._player.stop()
        self._preview_track = None
        self._preview_track_id = ""
        self.search_button.setEnabled(False)
        self.status_label.setText(f"正在通过 {source['name']} 搜索…")
        self._search_worker = AudioSourceSearchWorker(source, query, self)
        self._search_worker.completed.connect(self._search_completed)
        self._search_worker.failed.connect(self._operation_failed)
        self._search_worker.finished.connect(
            lambda: self.search_button.setEnabled(True)
        )
        self._search_worker.start()

    def _search_completed(self, tracks):
        self._tracks = list(tracks)
        self.content_tabs.setCurrentIndex(0)
        self._render_tracks(self._tracks)
        self.status_label.setText(f"找到 {len(self._tracks)} 首歌曲。")

    def _selected_track(self) -> dict | None:
        rows = self.results_table.selectionModel().selectedRows()
        row = rows[0].row() if rows else -1
        return (
            self._display_tracks[row]
            if 0 <= row < len(self._display_tracks)
            else None
        )

    def _show_selection(self):
        track = self._selected_track()
        if track is None:
            if self.content_tabs.currentIndex() == 0:
                self.stage_download_button.setEnabled(False)
            return
        if self.content_tabs.currentIndex() != 0:
            return
        self._download_target = track
        self._download_source = self._current_source()
        self.preview_title.setText(track.get("title") or "未命名歌曲")
        self.preview_artist.setText(
            " · ".join(
                value
                for value in (track.get("artist"), track.get("album"))
                if value
            )
            or "未知艺术家"
        )
        self.preview_cover.setText(
            (str(track.get("title") or "♪").strip()[:1] or "♪").upper()
        )
        self.track_title.setText(
            " · ".join(
                value for value in (track.get("title"), track.get("artist")) if value
            )
        )
        self.quality_combo.clear()
        for quality in track.get("qualities", []):
            labels = {
                "128k": "标准 128 kbps",
                "320k": "高品质 320 kbps",
                "flac": "无损 FLAC",
                "flac24bit": "Hi-Res 24-bit FLAC",
            }
            self.quality_combo.addItem(labels.get(quality, quality), quality)
        self.stage_download_button.setEnabled(bool(track.get("qualities")))
        self.download_button.setEnabled(False)

    @staticmethod
    def _track_identity(track: dict | None) -> str:
        if not track:
            return ""
        info = track.get("music_info")
        if isinstance(info, dict):
            value = (
                info.get("songmid")
                or info.get("songId")
                or info.get("hash")
                or track.get("id")
            )
        else:
            value = track.get("id")
        return f"{value}|{track.get('title', '')}|{track.get('artist', '')}"

    def _open_download_record(self):
        if self._download_target is not None:
            self.content_tabs.setCurrentIndex(1)

    def _toggle_preview(self, *_args):
        if self.content_tabs.currentIndex() != 0:
            return
        track = self._selected_track()
        source = self._current_source()
        if track is None or source is None:
            return
        identity = self._track_identity(track)
        if identity == self._preview_track_id and not self._player.source().isEmpty():
            if (
                self._player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState
            ):
                self._player.pause()
            else:
                self._playback_session.play(self._player)
            return
        if self._preview_worker and self._preview_worker.isRunning():
            return
        rows = self.results_table.selectionModel().selectedRows()
        track_index = rows[0].row() if rows else 0
        source_index = self.source_tabs.currentIndex()
        self._preview_token += 1
        token = self._preview_token
        self.preview_play_button.setEnabled(False)
        self.preview_play_button.setToolTip("正在验证可试听地址…")
        self.status_label.setText(
            f"正在验证：{track.get('title', '未命名歌曲')}；"
            "不可播放时会自动尝试其他结果与音源…"
        )
        self._preview_worker = AudioPreviewResolveWorker(
            token,
            self._sources,
            source_index,
            self._tracks,
            track_index,
            self.search_edit.text(),
            self,
        )
        self._preview_worker.completed.connect(self._preview_resolved)
        self._preview_worker.failed.connect(self._preview_failed)
        self._preview_worker.start()

    def _preview_resolved(self, result):
        if result.get("token") != self._preview_token:
            return
        resolved_source_index = int(result.get("source_index", -1))
        resolved_track_index = int(result.get("track_index", 0))
        if 0 <= resolved_source_index < len(self._sources):
            if resolved_source_index != self.source_tabs.currentIndex():
                self.source_tabs.blockSignals(True)
                self.source_tabs.setCurrentIndex(resolved_source_index)
                self.source_tabs.blockSignals(False)
                self._tracks = [dict(track) for track in result.get("tracks", [])]
                self._render_tracks(self._tracks)
            if self._tracks:
                resolved_track_index = max(
                    0, min(resolved_track_index, len(self._tracks) - 1)
                )
                self.results_table.selectRow(resolved_track_index)
                self.results_table.scrollToItem(
                    self.results_table.item(resolved_track_index, 1)
                )
        self.preview_play_button.setEnabled(True)
        self.preview_play_button.setToolTip("播放")
        self._preview_track = dict(result["track"])
        self._preview_track_id = self._track_identity(self._preview_track)
        self._download_source = dict(result.get("source") or {})
        self._download_target = dict(self._preview_track)
        self._player.stop()
        self._player.setSource(QUrl(str(result["url"])))
        self._playback_session.play(self._player)
        source_name = self._download_source.get("name", "当前音源")
        attempts = int(result.get("attempts", 1))
        prefix = "已自动切换并播放" if attempts > 1 else "正在播放"
        self.status_label.setText(
            f"{prefix}：{self._preview_track.get('title', '未命名歌曲')}"
            f" · {source_name}"
        )

    def _preview_failed(self, result):
        if result.get("token") != self._preview_token:
            return
        self.preview_play_button.setEnabled(True)
        self.preview_play_button.setToolTip("重试试听")
        self._preview_track = None
        self._preview_track_id = ""
        self._player.stop()
        self.preview_slider.setValue(0)
        self.preview_time.setText("00:00 / 00:00")
        message = str(result.get("message") or "无法获取试听地址。")
        self.status_label.setText(f"当前歌曲不可试听：{message}")

        # Keep the failure local to the selected result.  A blocking warning
        # dialog interrupts browsing and made a normal source limitation look
        # like the whole download workspace was broken.
        rows = self.results_table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            for column in range(self.results_table.columnCount()):
                item = self.results_table.item(row, column)
                if item is not None:
                    item.setToolTip(message)

    def _play_adjacent(self, offset: int):
        if not self._tracks:
            return
        rows = self.results_table.selectionModel().selectedRows()
        current = rows[0].row() if rows else 0
        target = (current + offset) % len(self._tracks)
        self.results_table.selectRow(target)
        self.results_table.scrollToItem(self.results_table.item(target, 1))
        self._toggle_preview()

    def _seek_preview(self, value: int):
        if self._player.duration() > 0:
            self._player.setPosition(max(0, min(value, self._player.duration())))

    def _preview_position_changed(self, position: int):
        if not self.preview_slider.isSliderDown():
            self.preview_slider.setValue(position)
        self.preview_time.setText(
            f"{self._format_milliseconds(position)} / "
            f"{self._format_milliseconds(self._player.duration())}"
        )

    def _preview_duration_changed(self, duration: int):
        self.preview_slider.setRange(0, max(0, duration))
        self._preview_position_changed(self._player.position())

    def _preview_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        icon = (
            QStyle.StandardPixmap.SP_MediaPause
            if playing
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.preview_play_button.setIcon(self.style().standardIcon(icon))
        self.preview_play_button.setToolTip("暂停" if playing else "播放")

    def _preview_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._tracks:
            self._play_adjacent(1)

    def _preview_player_error(self, _error, message: str):
        if message:
            self.status_label.setText(f"试听失败：{message}")

    @staticmethod
    def _format_milliseconds(value: int) -> str:
        seconds = max(0, int(value // 1000))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _browse_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            self.directory_edit.text(),
        )
        if directory:
            self.directory_edit.setText(directory)

    def _start_download(self):
        source = self._download_source
        track = self._download_target
        quality = self.quality_combo.currentData()
        directory = self.directory_edit.text().strip()
        if source is None or track is None or not quality or not directory:
            return
        output_path = str(Path(directory) / suggested_filename(track, quality))
        self.download_button.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("正在解析并下载音频…")
        self._download_worker = AudioDownloadWorker(
            source,
            track,
            quality,
            output_path,
            self,
        )
        self._download_worker.progress_changed.connect(self.progress.setValue)
        self._download_worker.completed.connect(self._download_finished)
        self._download_worker.failed.connect(self._operation_failed)
        self._download_worker.finished.connect(
            lambda: self.download_button.setEnabled(
                self.content_tabs.currentIndex() == 1
                and self._download_target is not None
            )
        )
        self._download_worker.start()

    def _download_finished(self, output_path: str):
        self.status_label.setText(f"下载完成：{Path(output_path).name}")
        track = self._download_target or {}
        history_item = dict(track)
        history_item["output_path"] = output_path
        history_item["qualities"] = [self.quality_combo.currentData()]
        self._download_history.insert(0, history_item)
        self.content_tabs.setTabText(1, f"下载记录 {len(self._download_history)}")
        self.download_completed.emit(output_path)

    def _operation_failed(self, message: str):
        self.status_label.setText(message)
        QMessageBox.warning(self, "音频下载失败", message)
