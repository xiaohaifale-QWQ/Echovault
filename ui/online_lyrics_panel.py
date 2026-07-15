"""Fourth right-side tab for LRCLIB search and lyric reconciliation."""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.online_lyrics import (
    LyricsMatch,
    calibrate_lrc_with_reference,
    compare_lyrics,
    media_search_metadata,
    search_lrclib,
)


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


class OnlineLyricsPanel(QWidget):
    action_requested = pyqtSignal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._song = {}
        self._matches: list[LyricsMatch] = []
        self._duration = 0.0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        heading = QLabel("在线歌词匹配（LRCLIB）")
        heading.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        layout.addWidget(heading)

        form = QFormLayout()
        self.track_input = QLineEdit()
        self.artist_input = QLineEdit()
        self.album_input = QLineEdit()
        form.addRow("歌名:", self.track_input)
        form.addRow("歌手:", self.artist_input)
        form.addRow("专辑:", self.album_input)
        layout.addLayout(form)

        search_row = QHBoxLayout()
        self.current_file_label = QLabel("请先选择一个素材")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("font-size:11px;color:#666")
        search_row.addWidget(self.current_file_label, 1)
        self.search_button = QPushButton("搜索公开歌词库")
        self.search_button.clicked.connect(self._start_search)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["匹配", "歌名", "歌手", "时长", "同步"]
        )
        self.results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.currentCellChanged.connect(self._on_result_selected)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.results_table, 2)

        self.comparison_label = QLabel("选择结果后显示本地与在线歌词核对情况")
        self.comparison_label.setWordWrap(True)
        self.comparison_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.comparison_label)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("在线匹配歌词预览")
        layout.addWidget(self.preview, 2)

        action_row = QHBoxLayout()
        self.apply_button = QPushButton("下载同步歌词")
        self.apply_button.setToolTip("备份已有 LRC 后写入 LRCLIB 的同步歌词；不修改音频")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(lambda: self._request_action("apply"))
        action_row.addWidget(self.apply_button)
        self.calibrate_button = QPushButton("AI 核对并校准")
        self.calibrate_button.setToolTip("保留本地时间戳，只按在线参考修正歌词文字")
        self.calibrate_button.setEnabled(False)
        self.calibrate_button.clicked.connect(lambda: self._request_action("calibrate"))
        action_row.addWidget(self.calibrate_button)
        layout.addLayout(action_row)

        self.status_label = QLabel("公开库无需 API Key；搜索内容会发送到 LRCLIB。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:11px;color:#666")
        layout.addWidget(self.status_label)

    def show_song(self, song: dict):
        if not song or not song.get("path"):
            return
        self._song = dict(song)
        path = Path(song["path"])
        self._song["lrc_path"] = str(path.with_suffix(".lrc"))
        metadata = media_search_metadata(path)
        self.track_input.setText(metadata.track_name)
        self.artist_input.setText(metadata.artist_name)
        self.album_input.setText(metadata.album_name)
        self._duration = metadata.duration
        duration_text = (
            self._format_duration(metadata.duration) if metadata.duration else "未知时长"
        )
        self.current_file_label.setText(f"{path.name} · {duration_text}")
        self._matches = []
        self.results_table.setRowCount(0)
        self.preview.clear()
        self.comparison_label.setText("搜索后选择一条结果进行核对")
        self.apply_button.setEnabled(False)
        self.calibrate_button.setEnabled(False)
        self.status_label.setText("已读取素材信息，可以编辑歌名/歌手后搜索。")

    @staticmethod
    def _format_duration(duration: float) -> str:
        minutes, seconds = divmod(int(round(duration)), 60)
        return f"{minutes}:{seconds:02d}"

    def _start_search(self):
        track_name = self.track_input.text().strip()
        if not track_name:
            self.status_label.setText("请先填写歌名。")
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
            self.status_label.setText(f"找到 {len(self._matches)} 条结果，已按匹配度排序。")
        else:
            self.preview.clear()
            self.status_label.setText("LRCLIB 没有找到匹配结果，可调整歌名或歌手后重试。")

    def _show_search_error(self, message: str):
        self.search_button.setEnabled(True)
        self.status_label.setText(f"搜索失败：{message}")

    def _selected_match(self):
        row = self.results_table.currentRow()
        return self._matches[row] if 0 <= row < len(self._matches) else None

    def _on_result_selected(self, *_args):
        match = self._selected_match()
        if match is None:
            self.apply_button.setEnabled(False)
            self.calibrate_button.setEnabled(False)
            return
        reference = match.synced_lyrics or match.plain_lyrics
        self.preview.setPlainText(reference)
        lrc_path = Path(self._song.get("lrc_path", ""))
        local_exists = lrc_path.is_file()
        self.apply_button.setEnabled(match.has_synced_lyrics)
        self.calibrate_button.setEnabled(local_exists and bool(reference.strip()))
        self.refresh_local_comparison()

    def refresh_local_comparison(self):
        match = self._selected_match()
        if match is None:
            return
        lrc_path = Path(self._song.get("lrc_path", ""))
        if not lrc_path.is_file():
            self.comparison_label.setText("本地暂无 LRC；可直接下载带时间轴的在线歌词。")
            return
        try:
            local_content = lrc_path.read_text(encoding="utf-8")
            comparison = compare_lyrics(
                local_content, match.synced_lyrics or match.plain_lyrics
            )
        except (OSError, UnicodeError) as exc:
            self.comparison_label.setText(f"无法读取本地歌词：{exc}")
            return
        self.comparison_label.setText(
            f"文字相似度 {comparison['similarity'] * 100:.1f}% · "
            f"本地 {comparison['local_lines']} 行 / 在线 {comparison['reference_lines']} 行 · "
            "AI 校准会保留本地时间戳"
        )

    def _request_action(self, action: str):
        match = self._selected_match()
        media_path = self._song.get("path")
        if match is not None and media_path:
            self.action_requested.emit(str(media_path), match, action)
