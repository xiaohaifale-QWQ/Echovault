"""Batch automation workspace and background preparation workers."""

from pathlib import Path

from PyQt6.QtCore import QRect, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.cover_art import download_cover_art, search_cover_art_fast
from core.metadata import read_cover_art, write_cover_art, write_lyrics_tag
from core.online_lyrics import (
    apply_synced_lyrics,
    media_search_metadata,
    search_lrclib,
    select_best_synced_match,
)


class EmptyStateTextEdit(QTextEdit):
    """Log view with an intentional empty state before the first run."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.toPlainText().strip():
            return
        painter = QPainter(self.viewport())
        rect = self.viewport().rect().adjusted(32, 32, -32, -32)
        title_font = painter.font()
        title_font.setPointSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#334155"))
        center_y = rect.center().y()
        painter.drawText(
            QRect(rect.left(), center_y - 34, rect.width(), 30),
            Qt.AlignmentFlag.AlignCenter,
            "准备开始批量整理",
        )
        hint_font = painter.font()
        hint_font.setPointSize(10)
        hint_font.setBold(False)
        painter.setFont(hint_font)
        painter.setPen(QColor("#8492A6"))
        painter.drawText(
            QRect(rect.left(), center_y + 4, rect.width(), 42),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "右侧选择规则后开始，处理步骤和结果会实时显示在这里。",
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


class BatchPreparationWorker(QThread):
    """Apply cover and online-lyrics rules without blocking the interface."""

    progress = pyqtSignal(int, int, str, str, int)
    completed = pyqtSignal(object)

    def __init__(self, songs: list[dict], rules: dict, parent=None):
        super().__init__(parent)
        self.songs = list(songs)
        self.rules = dict(rules)

    def run(self):
        results: list[dict] = []
        fallback_files: list[str] = []
        total = len(self.songs)
        for index, song in enumerate(self.songs, start=1):
            media_path = Path(song["path"])
            item = {
                "path": str(media_path),
                "cover": "未执行",
                "lyrics": "未执行",
                "lrc_path": "",
            }
            metadata = None
            steps = int(self.rules.get("match_cover", False)) + int(
                self.rules.get("match_lyrics", False)
            )
            finished_steps = 0

            def emit(message: str, final: bool = False):
                if final:
                    percent = 100
                else:
                    percent = int(finished_steps / max(steps, 1) * 100)
                self.progress.emit(
                    index, total, media_path.name, message, max(4, percent)
                )

            if self.rules.get("match_cover"):
                emit("封面 · 正在读取标签")
                try:
                    if self.rules.get("skip_existing") and read_cover_art(
                        str(media_path)
                    ):
                        item["cover"] = "已有封面，已跳过"
                    else:
                        metadata = media_search_metadata(media_path)
                        emit("封面 · 正在搜索候选")
                        covers = search_cover_art_fast(
                            metadata.track_name,
                            artist_name=metadata.artist_name,
                            album_name=metadata.album_name,
                            limit=3,
                        )
                        if not covers:
                            item["cover"] = "未找到"
                        else:
                            image_data, mime_type = download_cover_art(
                                covers[0].image_url
                            )
                            write_cover_art(str(media_path), image_data, mime_type)
                            item["cover"] = "已写入"
                except Exception as exc:
                    item["cover"] = f"失败：{exc}"
                finished_steps += 1
                emit(f"封面 · {item['cover']}")

            if self.rules.get("match_lyrics"):
                lrc_path = media_path.with_suffix(".lrc")
                emit("歌词 · 正在检查本地文件")
                try:
                    if (
                        self.rules.get("skip_existing")
                        and lrc_path.is_file()
                        and lrc_path.stat().st_size > 0
                    ):
                        item["lyrics"] = "已有歌词，已跳过"
                        item["lrc_path"] = str(lrc_path)
                    elif song.get("instrumental"):
                        item["lyrics"] = "纯音乐，已跳过"
                    else:
                        metadata = metadata or media_search_metadata(media_path)
                        emit("歌词 · 正在搜索同步歌词")
                        matches = search_lrclib(
                            metadata.track_name,
                            artist_name=metadata.artist_name,
                            album_name=metadata.album_name,
                            duration=metadata.duration,
                        )
                        match = select_best_synced_match(
                            matches,
                            minimum_score=float(
                                self.rules.get("minimum_score", 80)
                            ),
                        )
                        if match is None:
                            item["lyrics"] = "在线未找到"
                            if self.rules.get("local_fallback"):
                                fallback_files.append(str(media_path))
                        else:
                            output, _backup = apply_synced_lyrics(lrc_path, match)
                            item["lyrics"] = f"已匹配 {match.score:.0f}%"
                            item["lrc_path"] = str(output)
                except Exception as exc:
                    item["lyrics"] = f"失败：{exc}"
                    if self.rules.get("local_fallback"):
                        fallback_files.append(str(media_path))
                finished_steps += 1
                emit(f"歌词 · {item['lyrics']}")
            elif self.rules.get("local_fallback"):
                lrc_path = media_path.with_suffix(".lrc")
                if not (self.rules.get("skip_existing") and lrc_path.is_file()):
                    fallback_files.append(str(media_path))
                else:
                    item["lrc_path"] = str(lrc_path)

            emit("当前文件处理完成", final=True)
            results.append(item)
        self.completed.emit(
            {
                "results": results,
                "fallback_files": list(dict.fromkeys(fallback_files)),
            }
        )


class BatchEmbedLyricsWorker(QThread):
    """Write final LRC content into media tags with live per-file feedback."""

    progress = pyqtSignal(int, int, str, str, int)
    completed = pyqtSignal(object)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.items = list(items)

    def run(self):
        results = []
        total = len(self.items)
        for index, (media_path, lrc_path) in enumerate(self.items, start=1):
            filename = Path(media_path).name
            self.progress.emit(index, total, filename, "标签 · 正在写入歌词", 35)
            try:
                lyrics = Path(lrc_path).read_text(encoding="utf-8")
                write_lyrics_tag(media_path, lyrics)
                result = {
                    "path": media_path,
                    "success": True,
                    "message": "标签 · 歌词写入完成",
                }
            except Exception as exc:
                result = {
                    "path": media_path,
                    "success": False,
                    "message": f"标签 · 写入失败：{exc}",
                }
            results.append(result)
            self.progress.emit(index, total, filename, result["message"], 100)
        self.completed.emit(results)


class BatchOperationsPanel(QWidget):
    """A rule-driven batch pipeline with a single start action."""

    batch_transcribe_requested = pyqtSignal()
    batch_translate_requested = pyqtSignal(str, str, str)
    batch_online_requested = pyqtSignal(bool, float)
    batch_pipeline_requested = pyqtSignal(object)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()
        self.reload_translation_settings()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        progress_card = QFrame()
        progress_card.setObjectName("batchPipelineCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(18, 16, 18, 16)
        progress_layout.setSpacing(10)
        progress_title = QLabel("实时处理进度")
        progress_title.setObjectName("batchSectionTitle")
        progress_layout.addWidget(progress_title)
        status_block = QFrame()
        status_block.setObjectName("batchStatusBlock")
        status_layout = QVBoxLayout(status_block)
        status_layout.setContentsMargins(12, 11, 12, 11)
        status_layout.setSpacing(8)
        self.scope_label = QLabel("当前素材：0 个")
        self.scope_label.setWordWrap(True)
        self.scope_label.setObjectName("batchScope")
        status_layout.addWidget(self.scope_label)
        self.current_file_label = QLabel("尚未开始 · 请先在右侧确认处理规则")
        self.current_file_label.setObjectName("batchCurrentFile")
        status_layout.addWidget(self.current_file_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("总进度 0%")
        status_layout.addWidget(self.progress)
        progress_layout.addWidget(status_block)
        log_title_row = QHBoxLayout()
        log_title = QLabel("执行日志")
        log_title.setStyleSheet("font-weight:700")
        log_title_row.addWidget(log_title)
        log_title_row.addStretch()
        self.log = EmptyStateTextEdit()
        self.log.setReadOnly(True)
        clear_log = QPushButton("清空日志")
        clear_log.clicked.connect(self.log.clear)
        log_title_row.addWidget(clear_log)
        progress_layout.addLayout(log_title_row)
        progress_layout.addWidget(self.log, 1)
        root.addWidget(progress_card, 7)

        rules_card = QFrame()
        rules_card.setObjectName("batchPipelineCard")
        rules_layout = QVBoxLayout(rules_card)
        rules_layout.setContentsMargins(18, 16, 18, 16)
        rules_layout.setSpacing(10)
        rules_title = QLabel("批量处理规则")
        rules_title.setObjectName("batchSectionTitle")
        rules_layout.addWidget(rules_title)
        rules_hint = QLabel("勾选需要的规则，任务会按从上到下的顺序执行。")
        rules_hint.setWordWrap(True)
        rules_hint.setObjectName("batchMuted")
        rules_layout.addWidget(rules_hint)

        rules_layout.addWidget(self._rule_section("01  在线匹配"))
        self.match_cover_checkbox = self._add_rule(
            rules_layout,
            "自动匹配封面", "在线搜索最佳封面并写入音频标签。", True
        )
        self.match_lyrics_checkbox = self._add_rule(
            rules_layout,
            "自动匹配同步歌词", "优先搜索高匹配度的在线 LRC 歌词。", True
        )
        threshold_row = QHBoxLayout()
        threshold_row.addSpacing(28)
        threshold_row.addWidget(QLabel("最低匹配分"))
        self.minimum_score = QSpinBox()
        self.minimum_score.setRange(50, 100)
        self.minimum_score.setValue(80)
        self.minimum_score.setSuffix("%")
        threshold_row.addWidget(self.minimum_score)
        threshold_row.addStretch()
        rules_layout.addLayout(threshold_row)
        rules_layout.addWidget(self._rule_section("02  本地兜底与翻译"))
        self.local_fallback_checkbox = self._add_rule(
            rules_layout,
            "在线未找到时本地识别",
            "只有在线歌词未命中时才调用当前识别引擎。",
            True,
        )
        self.translate_english_checkbox = self._add_rule(
            rules_layout,
            "英文歌词自动翻译", "仅翻译检测为英文的歌词，保留原始 LRC。", False
        )
        translation_row = QHBoxLayout()
        translation_row.addSpacing(28)
        translation_row.addWidget(QLabel("翻译引擎"))
        self.translation_engine = QComboBox()
        self.translation_engine.addItem("AI 翻译", "ai")
        self.translation_engine.addItem("本地翻译", "local")
        translation_row.addWidget(self.translation_engine, 1)
        rules_layout.addLayout(translation_row)
        rules_layout.addWidget(self._rule_section("03  写入与保护"))
        self.embed_lyrics_checkbox = self._add_rule(
            rules_layout,
            "将最终歌词写入音频标签",
            "在保留独立 LRC 的同时写入媒体内嵌歌词。",
            False,
        )
        self.skip_existing_checkbox = self._add_rule(
            rules_layout,
            "跳过已有封面或歌词", "避免重复搜索和覆盖已经整理好的内容。", True
        )
        rules_layout.addStretch()
        self.rule_summary = QLabel("将处理 0 个素材")
        self.rule_summary.setObjectName("batchMuted")
        rules_layout.addWidget(self.rule_summary)
        self.start_pipeline_button = QPushButton("开始批量处理")
        self.start_pipeline_button.setObjectName("primaryAction")
        self.start_pipeline_button.setMinimumHeight(46)
        self.start_pipeline_button.clicked.connect(self._request_pipeline)
        rules_layout.addWidget(self.start_pipeline_button)
        root.addWidget(rules_card, 3)

        self._active_task = ""
        self._last_log_entry = ""
        self._scope_total = 0
        self.translate_english_checkbox.toggled.connect(
            self.translation_engine.setEnabled
        )
        self.translation_engine.setEnabled(False)
        self.setStyleSheet(
            """
            QFrame#batchPipelineCard {
                background:#FFFFFF;
                border:1px solid #D8E0EA;
                border-radius:12px;
            }
            QFrame#batchStatusBlock {
                background:#F4F8FD;
                border:1px solid #E0E8F2;
                border-radius:9px;
            }
            QFrame#batchRuleRow {
                background:#FAFBFD;
                border:1px solid #E3E8EF;
                border-radius:8px;
            }
            QFrame#batchRuleRow:hover {
                background:#F5F9FE;
                border-color:#B9D5F1;
            }
            QLabel#batchSectionTitle {
                color:#152238;
                font-size:16px;
                font-weight:700;
            }
            QLabel#batchScope {
                color:#315B86;
                font-weight:600;
            }
            QLabel#batchCurrentFile { color:#17233A; font-weight:700; }
            QLabel#batchMuted { color:#64748B; font-size:12px; }
            QLabel#batchRuleTitle { color:#1F2D42; font-weight:700; }
            QLabel#batchRuleDescription { color:#6B778A; font-size:11px; }
            QLabel#batchRuleSection {
                color:#7A8799;
                font-size:11px;
                font-weight:700;
                padding-top:4px;
            }
            QTextEdit {
                background:#FBFCFE;
                border:1px solid #E1E7EF;
                border-radius:8px;
                padding:10px;
            }
            """
        )

    @staticmethod
    def _rule_section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("batchRuleSection")
        return label

    @staticmethod
    def _add_rule(
        layout: QVBoxLayout, title: str, description: str, checked: bool
    ) -> QCheckBox:
        frame = QFrame()
        frame.setObjectName("batchRuleRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(9)
        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        checkbox.setToolTip(description)
        row.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("batchRuleTitle")
        description_label = QLabel(description)
        description_label.setObjectName("batchRuleDescription")
        description_label.setWordWrap(True)
        copy.addWidget(title_label)
        copy.addWidget(description_label)
        row.addLayout(copy, 1)
        layout.addWidget(frame)
        return checkbox

    @staticmethod
    def _select_data(combo: QComboBox, value: str):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def reload_translation_settings(self):
        if self.config is None:
            return
        self._select_data(self.translation_engine, self.config.translation_engine)

    def _request_pipeline(self):
        rules = {
            "match_cover": self.match_cover_checkbox.isChecked(),
            "match_lyrics": self.match_lyrics_checkbox.isChecked(),
            "local_fallback": self.local_fallback_checkbox.isChecked(),
            "translate_english": self.translate_english_checkbox.isChecked(),
            "embed_lyrics": self.embed_lyrics_checkbox.isChecked(),
            "skip_existing": self.skip_existing_checkbox.isChecked(),
            "minimum_score": float(self.minimum_score.value()),
            "translation_engine": self.translation_engine.currentData(),
            "translation_source": "en",
            "translation_target": "zh",
        }
        if not any(
            rules[key]
            for key in (
                "match_cover",
                "match_lyrics",
                "local_fallback",
                "translate_english",
                "embed_lyrics",
            )
        ):
            self.append_log("请至少勾选一项处理规则。")
            return
        self.batch_pipeline_requested.emit(rules)

    def update_scope(self, songs: list[dict]):
        total = len(songs)
        self._scope_total = total
        pending = sum(
            1
            for song in songs
            if not song.get("has_lrc") and not song.get("instrumental")
        )
        existing = sum(1 for song in songs if song.get("has_lrc"))
        self.scope_label.setText(
            f"当前素材：{total} 个  ·  待处理 {pending} 个  ·  已有歌词 {existing} 个"
        )
        self.rule_summary.setText(f"将处理 {total} 个素材")
        if not self._active_task:
            self.start_pipeline_button.setEnabled(total > 0)

    def begin_task(self, task: str, title: str, total: int):
        self._active_task = task
        self._last_log_entry = ""
        self.start_pipeline_button.setEnabled(False)
        self.progress.setRange(0, max(total, 1) * 100)
        self.progress.setValue(0)
        self.progress.setFormat(f"{title}  %p%")
        self.log.clear()
        self.current_file_label.setText(f"{title} · 准备中")
        self.append_log(f"开始 {title} · 共 {total} 个素材")

    def append_log(self, message: str):
        self.log.append(message)
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

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
        self.current_file_label.setText(f"[{current}/{total}] {filename}")
        entry = f"[{current}/{total}]  {filename}  ·  {message}"
        if entry != self._last_log_entry:
            self.append_log(entry)
            self._last_log_entry = entry

    def finish_task(self, summary: str):
        self.start_pipeline_button.setEnabled(self._scope_total > 0)
        self.progress.setValue(self.progress.maximum())
        self.current_file_label.setText("处理完成")
        self.append_log(f"\n{summary}")
        self._active_task = ""

    def begin_online_task(self, total: int):
        self.begin_task("online", "批量在线匹配", total)

    def show_online_progress(
        self, current: int, total: int, filename: str, message: str
    ):
        done_prefixes = ("已写入", "匹配", "没有", "失败")
        item_percent = 100 if message.startswith(done_prefixes) else 25
        self.show_task_progress(current, total, filename, message, item_percent)

    def finish_online_task(self, results: list[dict]):
        matched = sum(
            1 for item in results if item["status"] in {"matched", "applied"}
        )
        failed = sum(1 for item in results if item["status"] == "failed")
        self.finish_task(f"完成：匹配 {matched} 个，失败 {failed} 个。")
