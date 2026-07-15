"""Right-side workspace for all batch lyric operations."""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.online_lyrics import (
    apply_synced_lyrics,
    media_search_metadata,
    search_lrclib,
    select_best_synced_match,
)


class BatchOnlineLyricsWorker(QThread):
    """Search LRCLIB sequentially and optionally apply the best safe match."""

    progress = pyqtSignal(int, int, str, str)
    completed = pyqtSignal(list)

    def __init__(
        self,
        songs: list[dict],
        *,
        apply_best: bool,
        minimum_score: float,
        parent=None,
    ):
        super().__init__(parent)
        self.songs = list(songs)
        self.apply_best = apply_best
        self.minimum_score = minimum_score

    def run(self):
        results = []
        total = len(self.songs)
        for index, song in enumerate(self.songs, start=1):
            media_path = Path(song["path"])
            self.progress.emit(index, total, media_path.name, "正在读取歌曲信息…")
            try:
                metadata = media_search_metadata(media_path)
                self.progress.emit(index, total, media_path.name, "正在搜索 LRCLIB…")
                matches = search_lrclib(
                    metadata.track_name,
                    artist_name=metadata.artist_name,
                    album_name=metadata.album_name,
                    duration=metadata.duration,
                )
                match = select_best_synced_match(
                    matches, minimum_score=self.minimum_score
                )
                if match is None:
                    result = {
                        "path": str(media_path),
                        "status": "not_found",
                        "message": "没有达到阈值的同步歌词",
                    }
                elif self.apply_best:
                    output, backup = apply_synced_lyrics(
                        media_path.with_suffix(".lrc"), match
                    )
                    result = {
                        "path": str(media_path),
                        "status": "applied",
                        "score": match.score,
                        "record_id": match.record_id,
                        "lrc_path": str(output),
                        "backup": str(backup) if backup else "",
                        "message": f"已写入 {match.track_name}（{match.score:.0f}%）",
                    }
                else:
                    result = {
                        "path": str(media_path),
                        "status": "matched",
                        "score": match.score,
                        "record_id": match.record_id,
                        "message": f"匹配 {match.track_name}（{match.score:.0f}%）",
                    }
            except Exception as exc:
                result = {
                    "path": str(media_path),
                    "status": "failed",
                    "message": f"失败：{exc}",
                }
            results.append(result)
            self.progress.emit(index, total, media_path.name, result["message"])
        self.completed.emit(results)


class BatchOperationsPanel(QWidget):
    """Batch recognition, translation, and online matching controls."""

    batch_transcribe_requested = pyqtSignal()
    batch_translate_requested = pyqtSignal(str, str, str)
    batch_online_requested = pyqtSignal(bool, float)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()
        self.reload_translation_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        heading = QLabel("批量处理工作台")
        heading.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        layout.addWidget(heading)

        self.scope_label = QLabel("当前素材：0 个")
        self.scope_label.setWordWrap(True)
        self.scope_label.setStyleSheet("color:#666")
        layout.addWidget(self.scope_label)

        recognition_group = QGroupBox("批量识别")
        recognition_layout = QVBoxLayout(recognition_group)
        recognition_layout.addWidget(
            QLabel("识别当前列表里尚未生成 LRC、且未标记为纯音乐的素材。")
        )
        self.batch_transcribe_button = QPushButton("开始批量识别")
        self.batch_transcribe_button.setMinimumHeight(36)
        self.batch_transcribe_button.clicked.connect(
            self.batch_transcribe_requested.emit
        )
        recognition_layout.addWidget(self.batch_transcribe_button)
        layout.addWidget(recognition_group)

        translation_group = QGroupBox("批量翻译")
        translation_layout = QVBoxLayout(translation_group)
        translation_row = QHBoxLayout()
        self.translation_engine = QComboBox()
        self.translation_engine.addItem("AI 翻译", "ai")
        self.translation_engine.addItem("本地库", "local")
        translation_row.addWidget(self.translation_engine)
        self.translation_source = QComboBox()
        self.translation_target = QComboBox()
        self.translation_source.addItem("自动检测", "auto")
        for label, code in [("中", "zh"), ("英", "en"), ("日", "ja"), ("韩", "ko")]:
            self.translation_target.addItem(label, code)
        translation_row.addWidget(self.translation_source)
        translation_row.addWidget(QLabel("→"))
        translation_row.addWidget(self.translation_target)
        translation_layout.addLayout(translation_row)
        self.batch_translate_button = QPushButton("开始批量翻译")
        self.batch_translate_button.setMinimumHeight(36)
        self.batch_translate_button.clicked.connect(self._request_translation)
        translation_layout.addWidget(self.batch_translate_button)
        layout.addWidget(translation_group)

        online_group = QGroupBox("批量在线匹配")
        online_layout = QVBoxLayout(online_group)
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("最低匹配分："))
        self.minimum_score = QSpinBox()
        self.minimum_score.setRange(50, 100)
        self.minimum_score.setValue(80)
        self.minimum_score.setSuffix("%")
        threshold_row.addWidget(self.minimum_score)
        threshold_row.addStretch()
        online_layout.addLayout(threshold_row)
        self.apply_best_checkbox = QCheckBox("自动写入最佳同步歌词（已有 LRC 先备份）")
        online_layout.addWidget(self.apply_best_checkbox)
        self.batch_online_button = QPushButton("开始批量在线匹配")
        self.batch_online_button.setMinimumHeight(36)
        self.batch_online_button.clicked.connect(
            lambda: self.batch_online_requested.emit(
                self.apply_best_checkbox.isChecked(),
                float(self.minimum_score.value()),
            )
        )
        online_layout.addWidget(self.batch_online_button)
        layout.addWidget(online_group)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("批量任务进度与结果会显示在这里。")
        layout.addWidget(self.log, 1)
        self._active_task = ""
        self._last_log_entry = ""

    @staticmethod
    def _select_data(combo: QComboBox, value: str):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def reload_translation_settings(self):
        if self.config is None:
            return
        self._select_data(self.translation_engine, self.config.translation_engine)
        self._select_data(self.translation_source, "auto")
        self._select_data(
            self.translation_target, self.config.translation_target_language
        )

    def _request_translation(self):
        self.batch_translate_requested.emit(
            self.translation_engine.currentData(),
            self.translation_source.currentData(),
            self.translation_target.currentData(),
        )

    def update_scope(self, songs: list[dict]):
        total = len(songs)
        pending = sum(
            1
            for song in songs
            if not song.get("has_lrc") and not song.get("instrumental")
        )
        translatable = sum(1 for song in songs if song.get("has_lrc"))
        self.scope_label.setText(
            f"当前素材：{total} 个 · 待识别 {pending} 个 · 可翻译 {translatable} 个"
        )

    def begin_task(self, task: str, title: str, total: int):
        """Start a shared live log for recognition, translation, or matching."""

        self._active_task = task
        self._last_log_entry = ""
        for button in (
            self.batch_transcribe_button,
            self.batch_translate_button,
            self.batch_online_button,
        ):
            button.setEnabled(False)
        self.progress.setRange(0, max(total, 1) * 100)
        self.progress.setValue(0)
        self.progress.setFormat(f"{title} %p%")
        self.progress.setVisible(True)
        self.log.clear()
        self.log.append(f"开始{title}：共 {total} 个素材。")

    def show_task_progress(
        self,
        current: int,
        total: int,
        filename: str,
        message: str,
        item_percent: int = 0,
    ):
        self.progress.setRange(0, max(total, 1) * 100)
        percent = max(0, min(100, item_percent))
        self.progress.setValue(max(0, current - 1) * 100 + percent)
        entry = f"[{current}/{total}] {filename}：{message}"
        if entry != self._last_log_entry:
            self.log.append(entry)
            self._last_log_entry = entry
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def finish_task(self, summary: str):
        for button in (
            self.batch_transcribe_button,
            self.batch_translate_button,
            self.batch_online_button,
        ):
            button.setEnabled(True)
        self.progress.setValue(self.progress.maximum())
        self.log.append(f"\n{summary}")
        self._active_task = ""

    def begin_online_task(self, total: int):
        self.begin_task("online", "批量在线匹配", total)

    def show_online_progress(
        self, current: int, total: int, filename: str, message: str
    ):
        item_percent = 100 if message.startswith(("已写入", "匹配", "没有", "失败")) else 25
        self.show_task_progress(current, total, filename, message, item_percent)

    def finish_online_task(self, results: list[dict]):
        matched = sum(
            1 for item in results if item["status"] in {"matched", "applied"}
        )
        failed = sum(1 for item in results if item["status"] == "failed")
        self.finish_task(f"完成：匹配 {matched} 个，失败 {failed} 个。")
