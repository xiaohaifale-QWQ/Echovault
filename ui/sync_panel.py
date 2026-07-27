"""Phone transfer workspace with LocalSend receive, review, and return."""

from __future__ import annotations

import difflib
import threading
from pathlib import Path

from PyQt6.QtCore import QRect, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.artifact_diff import ArtifactDiff, scan_session_diffs
from core.config import config_manager
from core.sync_engine import ConflictResolution, DiffType, SyncDirection, SyncEngine
from core.transfer_session import TransferSession, TransferSessionManager
from server.localsend_receiver import HTTP_PORT, LocalSendReceiver
from server.localsend_sender import LocalSendDevice, LocalSendSender

STATUS_TEXT = {
    "generated": "新生成",
    "modified": "已修改",
    "missing": "已删除",
    "unchanged": "未变化",
}
OPERATION_TEXT = {
    "transcription": "歌词识别",
    "translation": "歌词翻译",
    "online_lyrics": "在线歌词",
    "cover_art": "封面标签",
    "vocal_separation": "人声分离",
    "audio_enhancement": "音频增强",
    "video_aggregation": "视频汇总",
}


class EmptyStateTableWidget(QTableWidget):
    """A table that explains what to do instead of showing a blank white slab."""

    def __init__(self, rows, columns, title, hint, parent=None):
        super().__init__(rows, columns, parent)
        self._empty_title = title
        self._empty_hint = hint

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount():
            return
        painter = QPainter(self.viewport())
        rect = self.viewport().rect().adjusted(40, 40, -40, -40)
        painter.setPen(QColor("#334155"))
        title_font = painter.font()
        title_font.setPointSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        center_y = rect.center().y()
        title_rect = QRect(rect.left(), center_y - 34, rect.width(), 30)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignCenter,
            self._empty_title,
        )
        hint_font = painter.font()
        hint_font.setPointSize(10)
        hint_font.setBold(False)
        painter.setFont(hint_font)
        painter.setPen(QColor("#8492A6"))
        hint_rect = QRect(rect.left(), center_y + 4, rect.width(), 42)
        painter.drawText(
            hint_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self._empty_hint,
        )


class FolderSyncWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)

    def __init__(self, engine, plan, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.plan = plan

    def run(self):
        self.finished.emit(
            self.engine.execute_plan(
                self.plan,
                lambda current, total, filename: self.progress.emit(
                    current, total, filename
                ),
            )
        )


class FolderSyncPanel(QWidget):
    """Existing A/B folder synchronization kept as an advanced feature."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = SyncEngine()
        self._diffs = []
        self._plan = None
        self._setup_ui()
        config = config_manager.load()
        self.dir_b_input.setText(config.sync.remote_dir)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        paths = QFormLayout()
        self.dir_a_input = QLineEdit()
        self.dir_b_input = QLineEdit()
        paths.addRow("文件夹 A：", self._path_row(self.dir_a_input))
        paths.addRow("文件夹 B：", self._path_row(self.dir_b_input))
        layout.addLayout(paths)

        settings = QHBoxLayout()
        settings.addWidget(QLabel("方向："))
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("双向合并", SyncDirection.BIDIRECTIONAL.value)
        self.direction_combo.addItem("A → B", SyncDirection.A_TO_B.value)
        self.direction_combo.addItem("B → A", SyncDirection.B_TO_A.value)
        self.direction_combo.addItem("镜像 A → B", SyncDirection.MIRROR_A_TO_B.value)
        settings.addWidget(self.direction_combo)
        settings.addWidget(QLabel("冲突："))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("手动处理", ConflictResolution.MANUAL.value)
        self.conflict_combo.addItem("跳过", ConflictResolution.SKIP.value)
        settings.addWidget(self.conflict_combo)
        settings.addStretch()
        layout.addLayout(settings)

        actions = QHBoxLayout()
        compare = QPushButton("对比文件夹")
        compare.clicked.connect(self._compare)
        self.sync_button = QPushButton("执行文件夹同步")
        self.sync_button.setEnabled(False)
        self.sync_button.clicked.connect(self._sync)
        actions.addWidget(compare)
        actions.addWidget(self.sync_button)
        layout.addLayout(actions)

        self.summary = QLabel("")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件", "差异类型", "大小"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(190)
        layout.addWidget(self.table)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

    def _path_row(self, edit):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit)
        button = QPushButton("…")
        button.setFixedWidth(36)
        button.clicked.connect(lambda: self._browse(edit))
        layout.addWidget(button)
        return row

    def _browse(self, edit):
        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:
            edit.setText(directory)

    def set_dir_a(self, path):
        self.dir_a_input.setText(path)

    def _compare(self):
        directory_a = self.dir_a_input.text().strip()
        directory_b = self.dir_b_input.text().strip()
        if not directory_a or not directory_b:
            QMessageBox.warning(self, "提示", "请先选择两个电脑可访问的文件夹。")
            return
        try:
            self._diffs = self.engine.compare_directories(directory_a, directory_b)
        except Exception as exc:
            QMessageBox.critical(self, "文件夹对比失败", str(exc))
            return
        labels = {
            DiffType.ONLY_IN_A: "仅在 A",
            DiffType.ONLY_IN_B: "仅在 B",
            DiffType.NEWER_IN_A: "A 较新",
            DiffType.NEWER_IN_B: "B 较新",
            DiffType.CONFLICT: "冲突",
        }
        self.table.setRowCount(len(self._diffs))
        for row, diff in enumerate(self._diffs):
            self.table.setItem(row, 0, QTableWidgetItem(diff.file.relative_path))
            self.table.setItem(row, 1, QTableWidgetItem(labels.get(diff.diff_type, "")))
            self.table.setItem(row, 2, QTableWidgetItem(_format_size(diff.file.size)))
        self.summary.setText(f"发现 {len(self._diffs)} 个文件夹差异。")
        self.sync_button.setEnabled(bool(self._diffs))

    def _sync(self):
        direction = SyncDirection(self.direction_combo.currentData())
        self.engine.conflict_resolution = ConflictResolution(
            self.conflict_combo.currentData()
        )
        self._plan = self.engine.create_plan(
            self._diffs,
            direction,
            self.dir_a_input.text().strip(),
            self.dir_b_input.text().strip(),
        )
        if self._plan.files_with_conflict and (
            self.engine.conflict_resolution == ConflictResolution.MANUAL
        ):
            QMessageBox.warning(self, "存在冲突", "请先处理冲突，或选择跳过。")
            return
        message = (
            f"复制 {len(self._plan.files_to_copy)} 个文件，"
            f"删除 {len(self._plan.files_to_delete)} 个文件，继续吗？"
        )
        if QMessageBox.question(self, "确认文件夹同步", message) != (
            QMessageBox.StandardButton.Yes
        ):
            return
        if self._plan.files_to_delete and QMessageBox.warning(
            self,
            "确认删除",
            "镜像同步会永久删除 B 中多余的文件，确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.worker = FolderSyncWorker(self.engine, self._plan, self)
        self.worker.progress.connect(
            lambda current, total, _name: self.progress.setValue(current)
        )
        self.worker.finished.connect(self._sync_finished)
        self.progress.setMaximum(max(1, self._plan.total_operations))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.sync_button.setEnabled(False)
        self.worker.start()

    def _sync_finished(self, stats):
        self.progress.setVisible(False)
        self.sync_button.setEnabled(True)
        QMessageBox.information(
            self,
            "文件夹同步完成",
            f"复制 {stats['copied']}，删除 {stats['deleted']}，"
            f"跳过 {stats['skipped']}，错误 {stats['errors']}。",
        )


class SessionIndexWorker(QThread):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, manager, payload, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.payload = payload

    def run(self):
        try:
            session = self.manager.create_session(
                session_id=self.payload["session_id"],
                sender=self.payload.get("sender", {}),
                workspace=self.payload["workspace"],
                files=self.payload.get("files", []),
                received_at=self.payload.get("received_at"),
            )
            self.finished.emit(session.session_id)
        except Exception as exc:
            self.failed.emit(str(exc))


class DiffScanWorker(QThread):
    finished = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, session, strict_hash, parent=None):
        super().__init__(parent)
        self.session = session
        self.strict_hash = strict_hash

    def run(self):
        try:
            self.finished.emit(
                self.session,
                scan_session_diffs(self.session, strict_hash=self.strict_hash),
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class SendWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, sender, device, files, parent=None):
        super().__init__(parent)
        self.sender = sender
        self.device = device
        self.files = files
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            results = self.sender.send_files(
                self.device,
                self.files,
                cancel_event=self.cancel_event,
                progress=lambda path, _sent, _size, total, maximum: self.progress.emit(
                    int(total * 100 / maximum) if maximum else 0, Path(path).name
                ),
            )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class ArtifactPreviewDialog(QDialog):
    def __init__(self, diff: ArtifactDiff, parent=None):
        super().__init__(parent)
        self.diff = diff
        self.setWindowTitle(f"查看文件 - {Path(diff.path).name}")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"状态：{STATUS_TEXT.get(diff.status, diff.status)}　"
                f"大小：{_format_size(diff.size)}　路径：{diff.path}"
            )
        )
        content = QPlainTextEdit()
        content.setReadOnly(True)
        content.setPlainText(self._preview_text())
        layout.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        open_button = buttons.addButton("用系统程序打开", QDialogButtonBox.ButtonRole.ActionRole)
        open_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(diff.path))
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview_text(self):
        path = Path(self.diff.path)
        if path.suffix.lower() in {".lrc", ".txt", ".json", ".csv", ".md"} and path.is_file():
            current = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if self.diff.snapshot_path and Path(self.diff.snapshot_path).is_file():
                original = Path(self.diff.snapshot_path).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                return "\n".join(
                    difflib.unified_diff(
                        original,
                        current,
                        fromfile="接收时版本",
                        tofile="当前版本",
                        lineterm="",
                    )
                )
            return "\n".join(current)
        details = [
            f"文件名：{path.name}",
            f"位置：{path}",
            f"大小：{_format_size(self.diff.size)}",
            "处理来源："
            + OPERATION_TEXT.get(
                self.diff.operation, self.diff.operation or "自动扫描"
            ),
        ]
        if path.suffix.lower() in {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".mp4"}:
            try:
                from core.audio_utils import get_audio_info

                info = get_audio_info(str(path))
                details.extend(
                    [
                        f"时长：{info.get('duration', 0):.2f} 秒",
                        f"采样率：{info.get('sample_rate', 0)} Hz",
                        f"声道：{info.get('channels', 0)}",
                    ]
                )
            except Exception:
                pass
        return "\n".join(details)


class SyncPanel(QWidget):
    """Primary phone workflow: receive -> review artifacts -> send back."""

    _device_discovered = pyqtSignal(object)
    _session_completed = pyqtSignal(object)
    _receive_progress = pyqtSignal(int, int, str)
    _file_received = pyqtSignal(str)

    def __init__(self, parent=None, session_manager=None):
        super().__init__(parent)
        self.config = config_manager.load()
        self.session_manager = session_manager or TransferSessionManager(
            outbox_dir=self.config.transfer.outbox_dir or None
        )
        self._localsend = None
        self._devices: dict[str, LocalSendDevice] = {}
        self._sessions: list[TransferSession] = []
        self._diffs: list[ArtifactDiff] = []
        self._selected_paths: set[str] = set()
        self._manual_diffs: list[ArtifactDiff] = []
        self._selection_initialized: set[str] = set()
        self._current_session: TransferSession | None = None
        self._setup_ui()
        self._device_discovered.connect(self._on_device_discovered_ui)
        self._session_completed.connect(self._on_session_completed_ui)
        self._receive_progress.connect(self._on_receive_progress_ui)
        self._file_received.connect(self._on_file_received_ui)
        self._refresh_sessions()
        if self.config.transfer.auto_start_receiver and self.receive_dir_input.text():
            self.receiver_button.setChecked(True)

    def _setup_ui(self):
        self.send_page = QWidget(self)
        self.send_page.setObjectName("phoneSendPage")
        send_page_layout = QVBoxLayout(self.send_page)
        send_page_layout.setContentsMargins(14, 14, 14, 14)
        send_page_layout.setSpacing(10)

        self.receive_page = QWidget(self)
        self.receive_page.setObjectName("phoneReceivePage")
        receive_page_layout = QVBoxLayout(self.receive_page)
        receive_page_layout.setContentsMargins(14, 14, 14, 14)
        receive_page_layout.setSpacing(10)

        self.advanced_sync_page = QWidget(self)
        self.advanced_sync_page.setObjectName("advancedFolderSyncPage")
        advanced_page_layout = QVBoxLayout(self.advanced_sync_page)
        advanced_page_layout.setContentsMargins(14, 14, 14, 14)
        advanced_page_layout.setSpacing(10)

        # 接收：左侧实时队列，右侧服务设置。
        receive_columns = QHBoxLayout()
        receive_columns.setSpacing(12)
        receive_queue_card = QFrame()
        receive_queue_card.setObjectName("transferCard")
        receive_queue_layout = QVBoxLayout(receive_queue_card)
        receive_queue_layout.setContentsMargins(16, 14, 16, 14)
        receive_queue_layout.setSpacing(10)
        receive_title_row = QHBoxLayout()
        receive_title = QLabel("接收队列")
        receive_title.setObjectName("transferSectionTitle")
        receive_title_row.addWidget(receive_title)
        receive_count = QLabel("手机传来的文件会自动出现在这里")
        receive_count.setObjectName("transferMuted")
        receive_title_row.addWidget(receive_count)
        receive_title_row.addStretch()
        self.receive_filter_all = QPushButton("全部")
        self.receive_filter_all.setCheckable(True)
        self.receive_filter_all.setChecked(True)
        self.receive_filter_all.setObjectName("transferFilter")
        self.receive_filter_active = QPushButton("传输中")
        self.receive_filter_active.setCheckable(True)
        self.receive_filter_active.setObjectName("transferFilter")
        self.receive_filter_done = QPushButton("已完成")
        self.receive_filter_done.setCheckable(True)
        self.receive_filter_done.setObjectName("transferFilter")
        self.receive_filter_group = QButtonGroup(self)
        self.receive_filter_group.setExclusive(True)
        for button, mode in (
            (self.receive_filter_all, "all"),
            (self.receive_filter_active, "active"),
            (self.receive_filter_done, "done"),
        ):
            self.receive_filter_group.addButton(button)
            button.clicked.connect(
                lambda _checked, selected=mode: self._filter_receive_queue(selected)
            )
        receive_title_row.addWidget(self.receive_filter_all)
        receive_title_row.addWidget(self.receive_filter_active)
        receive_title_row.addWidget(self.receive_filter_done)
        self.clear_receive_history_button = QPushButton("清除记录")
        self.clear_receive_history_button.clicked.connect(
            lambda: self.receive_queue.setRowCount(0)
        )
        receive_title_row.addWidget(self.clear_receive_history_button)
        receive_queue_layout.addLayout(receive_title_row)
        self.receive_queue = EmptyStateTableWidget(
            0,
            4,
            "等待接收文件",
            "开启右侧接收服务后，在手机 LocalSend 中选择本机即可发送。",
        )
        self.receive_queue.setHorizontalHeaderLabels(["文件", "来源", "进度", "状态"])
        receive_header = self.receive_queue.horizontalHeader()
        receive_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            receive_header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.receive_queue.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.receive_queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.receive_queue.verticalHeader().setVisible(False)
        receive_queue_layout.addWidget(self.receive_queue, 1)
        self.receive_progress = QProgressBar()
        self.receive_progress.setVisible(False)
        receive_queue_layout.addWidget(self.receive_progress)
        self.recent_received = QLabel("")
        self.recent_received.setVisible(False)
        receive_queue_layout.addWidget(self.recent_received)
        receive_columns.addWidget(receive_queue_card, 7)

        receive_settings_card = QFrame()
        receive_settings_card.setObjectName("transferSideCard")
        receive_settings_layout = QVBoxLayout(receive_settings_card)
        receive_settings_layout.setContentsMargins(16, 14, 16, 14)
        receive_settings_layout.setSpacing(12)
        settings_title = QLabel("接收设置")
        settings_title.setObjectName("transferSectionTitle")
        receive_settings_layout.addWidget(settings_title)
        service_row = QHBoxLayout()
        service_copy = QVBoxLayout()
        service_label = QLabel("本机接收服务")
        service_label.setStyleSheet("font-weight:700")
        self.receiver_status = QLabel("● 未开启")
        self.receiver_status.setObjectName("transferStatus")
        service_copy.addWidget(service_label)
        service_copy.addWidget(self.receiver_status)
        service_row.addLayout(service_copy, 1)
        self.receiver_button = QPushButton("开启接收")
        self.receiver_button.setCheckable(True)
        self.receiver_button.setMinimumHeight(38)
        self.receiver_button.clicked.connect(self._toggle_receiver)
        service_row.addWidget(self.receiver_button)
        service_card = QFrame()
        service_card.setObjectName("serviceStatusCard")
        service_card_layout = QVBoxLayout(service_card)
        service_card_layout.setContentsMargins(12, 10, 12, 10)
        service_card_layout.addLayout(service_row)
        receive_settings_layout.addWidget(service_card)
        device_alias = QLabel(f"本机设备名：{self.config.transfer.device_alias or 'Echovault-PC'}")
        device_alias.setObjectName("transferMuted")
        receive_settings_layout.addWidget(device_alias)
        receive_settings_layout.addWidget(self._transfer_divider())
        path_label = QLabel("保存到文件夹")
        path_label.setStyleSheet("font-weight:600")
        receive_settings_layout.addWidget(path_label)
        self.receive_dir_input = QLineEdit(self.config.transfer.receive_dir)
        self.receive_dir_input.setPlaceholderText("选择手机文件接收目录…")
        receive_settings_layout.addWidget(self.receive_dir_input)
        path_actions = QHBoxLayout()
        self.browse_receive_button = QPushButton("选择")
        self.browse_receive_button.clicked.connect(self._browse_receive_dir)
        path_actions.addWidget(self.browse_receive_button)
        self.open_receive_button = QPushButton("打开")
        self.open_receive_button.clicked.connect(self._open_receive_dir)
        path_actions.addWidget(self.open_receive_button)
        path_actions.addStretch()
        receive_settings_layout.addLayout(path_actions)
        self.auto_accept_checkbox = QCheckBox("自动接受来自已配对设备的文件")
        self.auto_accept_checkbox.setChecked(True)
        receive_settings_layout.addWidget(self.auto_accept_checkbox)
        self.receive_notify_checkbox = QCheckBox("完成后显示通知")
        self.receive_notify_checkbox.setChecked(True)
        receive_settings_layout.addWidget(self.receive_notify_checkbox)
        receive_settings_layout.addStretch()
        self.receive_network_status = QLabel("▮▮  局域网连接正常")
        self.receive_network_status.setObjectName("transferSuccess")
        receive_settings_layout.addWidget(self.receive_network_status)
        receive_columns.addWidget(receive_settings_card, 3)
        receive_page_layout.addLayout(receive_columns, 1)

        # 发送：左侧待发送文件，右侧设备与发送设置。
        send_columns = QHBoxLayout()
        send_columns.setSpacing(12)
        task_group = QFrame()
        task_group.setObjectName("transferCard")
        task_layout = QVBoxLayout(task_group)
        task_layout.setContentsMargins(16, 14, 16, 14)
        task_layout.setSpacing(10)
        task_title_row = QHBoxLayout()
        task_title = QLabel("待发送文件")
        task_title.setObjectName("transferSectionTitle")
        task_title_row.addWidget(task_title)
        queue_hint = QLabel("从处理任务载入，或直接添加本地文件")
        queue_hint.setObjectName("transferMuted")
        task_title_row.addWidget(queue_hint)
        task_title_row.addStretch()
        self.add_send_files_button = QPushButton("添加文件")
        self.add_send_files_button.clicked.connect(self._add_send_files)
        task_title_row.addWidget(self.add_send_files_button)
        self.add_send_folder_button = QPushButton("添加文件夹")
        self.add_send_folder_button.clicked.connect(self._add_send_folder)
        task_title_row.addWidget(self.add_send_folder_button)
        task_layout.addLayout(task_title_row)
        task_row = QHBoxLayout()
        self.session_combo = QComboBox()
        self.session_combo.currentIndexChanged.connect(self._load_selected_session)
        self.session_combo.setMinimumHeight(38)
        self.session_combo.setPlaceholderText("选择处理任务（可选）")
        task_row.addWidget(self.session_combo, 1)
        self.send_search_input = QLineEdit()
        self.send_search_input.setPlaceholderText("搜索文件")
        self.send_search_input.setMinimumHeight(38)
        self.send_search_input.textChanged.connect(self._filter_send_table)
        task_row.addWidget(self.send_search_input, 1)
        task_layout.addLayout(task_row)
        outbox_row = QHBoxLayout()
        self.outbox_path_label = QLabel(str(self.session_manager.outbox_dir))
        self.outbox_path_label.setWordWrap(True)
        self.outbox_path_label.setObjectName("transferMuted")
        self.outbox_path_label.setVisible(False)
        self.task_status = QLabel("当前没有处理任务，可使用右上角按钮添加文件")
        self.task_status.setObjectName("transferMuted")
        outbox_row.addWidget(self.task_status, 1)
        open_outbox = QPushButton("打开结果目录")
        open_outbox.clicked.connect(self._open_outbox)
        outbox_row.addWidget(open_outbox)
        task_layout.addLayout(outbox_row)

        result_toolbar = QHBoxLayout()
        result_toolbar.addStretch()
        self.select_all_diffs_button = QPushButton("全选差异")
        self.select_all_diffs_button.clicked.connect(self._select_all_diffs)
        result_toolbar.addWidget(self.select_all_diffs_button)
        self.clear_selection_button = QPushButton("清除选择")
        self.clear_selection_button.clicked.connect(self._clear_selection)
        result_toolbar.addWidget(self.clear_selection_button)
        preview = QPushButton("预览")
        preview.clicked.connect(self._preview_selected)
        result_toolbar.addWidget(preview)
        open_file = QPushButton("打开")
        open_file.clicked.connect(self._open_selected_file)
        result_toolbar.addWidget(open_file)
        task_layout.addLayout(result_toolbar)

        self.diff_table = EmptyStateTableWidget(
            0,
            6,
            "还没有待发送文件",
            "点击“添加文件”或“添加文件夹”，也可以从上方选择一个处理任务。",
        )
        self.diff_table.setHorizontalHeaderLabels(
            ["选择", "名称", "来源", "格式", "大小", "状态"]
        )
        header = self.diff_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.setMinimumHeight(170)
        self.diff_table.verticalHeader().setVisible(False)
        self.diff_table.itemChanged.connect(self._selection_changed)
        self.diff_table.cellDoubleClicked.connect(lambda _row, _column: self._preview_selected())
        task_layout.addWidget(self.diff_table, 1)
        queue_footer = QHBoxLayout()
        self.selection_summary = QLabel("已选择 0 项 · 0 B")
        self.selection_summary.setStyleSheet("font-weight:600")
        queue_footer.addWidget(self.selection_summary)
        queue_footer.addStretch()
        self.remove_send_item_button = QPushButton("移除")
        self.remove_send_item_button.clicked.connect(self._remove_current_send_item)
        queue_footer.addWidget(self.remove_send_item_button)
        self.clear_send_queue_button = QPushButton("清空")
        self.clear_send_queue_button.clicked.connect(self._clear_send_queue)
        queue_footer.addWidget(self.clear_send_queue_button)
        task_layout.addLayout(queue_footer)
        send_columns.addWidget(task_group, 7)

        send_group = QFrame()
        send_group.setObjectName("transferSideCard")
        send_layout = QVBoxLayout(send_group)
        send_layout.setContentsMargins(16, 14, 16, 14)
        send_layout.setSpacing(12)
        device_title_row = QHBoxLayout()
        device_title = QLabel("附近设备")
        device_title.setObjectName("transferSectionTitle")
        device_title_row.addWidget(device_title)
        device_title_row.addStretch()
        discover = QPushButton("↻ 刷新")
        discover.clicked.connect(self._refresh_devices)
        device_title_row.addWidget(discover)
        send_layout.addLayout(device_title_row)
        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumHeight(44)
        self.device_combo.addItem("未发现设备", None)
        self.device_combo.currentIndexChanged.connect(
            lambda _index: self._update_selection_summary()
        )
        device_row.addWidget(self.device_combo, 1)
        send_layout.addLayout(device_row)
        self.send_status = QLabel("确保电脑与手机位于同一局域网，然后点击刷新。")
        self.send_status.setWordWrap(True)
        self.send_status.setObjectName("transferMuted")
        send_layout.addWidget(self.send_status)
        self.device_help = QLabel(
            "连接设备\n"
            "1  手机与电脑连接同一局域网\n"
            "2  在手机打开 LocalSend\n"
            "3  点击“刷新”并选择发现的设备"
        )
        self.device_help.setObjectName("transferHelp")
        self.device_help.setWordWrap(True)
        send_layout.addWidget(self.device_help)
        self.send_progress = QProgressBar()
        self.send_progress.setVisible(False)
        send_layout.addWidget(self.send_progress)
        send_layout.addWidget(self._transfer_divider())
        send_settings_title = QLabel("发送设置")
        send_settings_title.setObjectName("transferSectionTitle")
        send_layout.addWidget(send_settings_title)
        send_layout.addWidget(QLabel("重名处理规则"))
        self.conflict_rule_combo = QComboBox()
        self.conflict_rule_combo.addItems(
            ["重名时自动重命名", "询问后处理", "跳过同名文件"]
        )
        send_layout.addWidget(self.conflict_rule_combo)
        self.open_on_phone_checkbox = QCheckBox("发送后在手机端打开")
        send_layout.addWidget(self.open_on_phone_checkbox)
        send_layout.addStretch()
        self.send_summary = QLabel("尚未选择文件")
        self.send_summary.setObjectName("transferMuted")
        self.send_summary.setWordWrap(True)
        send_layout.addWidget(self.send_summary)
        self.send_button = QPushButton("发送 0 个文件")
        self.send_button.setObjectName("primaryAction")
        self.send_button.setMinimumHeight(44)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._send_selected)
        send_layout.addWidget(self.send_button)
        self.cancel_send_button = QPushButton("取消")
        self.cancel_send_button.setVisible(False)
        self.cancel_send_button.clicked.connect(self._cancel_send)
        send_layout.addWidget(self.cancel_send_button)
        send_columns.addWidget(send_group, 3)
        send_page_layout.addLayout(send_columns, 1)

        self.advanced_group = QGroupBox("文件夹 A/B 同步")
        self.advanced_group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        advanced_layout = QVBoxLayout(self.advanced_group)
        self.folder_sync_panel = FolderSyncPanel()
        advanced_layout.addWidget(self.folder_sync_panel)
        advanced_page_layout.addWidget(self.advanced_group, 1)

        transfer_style = """
            QWidget#phoneSendPage,
            QWidget#phoneReceivePage,
            QWidget#advancedFolderSyncPage {
                background: #FFFFFF;
                border: 1px solid #D8E0EA;
                border-radius: 14px;
            }
            QFrame#transferCard {
                background: #FFFFFF;
                border: 1px solid #D8E0EA;
                border-radius: 12px;
            }
            QFrame#transferSideCard {
                background: #F9FBFE;
                border: 1px solid #D5DFEA;
                border-radius: 12px;
            }
            QFrame#serviceStatusCard {
                background: #F6F9FD;
                border: 1px solid #E1E8F0;
                border-radius: 9px;
            }
            QLabel#transferSectionTitle {
                color: #152238;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#transferMuted { color: #64748B; font-size: 12px; }
            QLabel#transferHelp {
                background: #EFF5FC;
                color: #526176;
                border: 1px solid #DDE8F4;
                border-radius: 8px;
                padding: 10px 12px;
            }
            QLabel#transferStatus { color: #64748B; font-weight: 600; }
            QLabel#transferSuccess { color: #2F9B63; font-weight: 600; }
            QPushButton#transferFilter:checked {
                background: #E8F2FD;
                color: #246FB8;
                border-color: #B9D5F1;
            }
            QTableWidget {
                background: #FBFCFE;
                alternate-background-color: #F7FAFD;
                border: 1px solid #E1E7EF;
                border-radius: 8px;
                gridline-color: #E9EEF4;
            }
            QHeaderView::section {
                background: #F4F7FB;
                color: #526176;
                border: none;
                border-bottom: 1px solid #E1E7EF;
                padding: 9px 8px;
                font-weight: 600;
            }
            """
        self.setStyleSheet(transfer_style)
        # These pages are later reparented into the main window's QTabWidget.
        # Bind the visual rules to each real page as well, otherwise they stop
        # inheriting SyncPanel's stylesheet and fall back to the gray workspace.
        for page in (
            self.send_page,
            self.receive_page,
            self.advanced_sync_page,
        ):
            page.setStyleSheet(transfer_style)

    @staticmethod
    def _transfer_divider():
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setStyleSheet("color:#E6EBF1")
        return divider

    def _add_send_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加待发送文件",
            "",
            "媒体与歌词 (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.opus *.lrc *.srt);;所有文件 (*)",
        )
        self._add_manual_paths(paths)

    def _add_send_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "添加待发送文件夹")
        if not directory:
            return
        supported = {
            ".mp3",
            ".flac",
            ".wav",
            ".m4a",
            ".aac",
            ".ogg",
            ".opus",
            ".lrc",
            ".srt",
        }
        paths = [
            str(path)
            for path in Path(directory).rglob("*")
            if path.is_file() and path.suffix.lower() in supported
        ]
        self._add_manual_paths(paths)

    def _add_manual_paths(self, paths):
        existing = {str(Path(item.path).resolve()) for item in self._manual_diffs}
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            self._manual_diffs.append(
                ArtifactDiff(
                    path=resolved,
                    relative_path=path.name,
                    status="generated",
                    size=path.stat().st_size,
                    operation="manual_import",
                )
            )
            self._selected_paths.add(resolved)
            existing.add(resolved)
        self._populate_diff_table()

    def _remove_current_send_item(self):
        diff = self._current_diff()
        if not isinstance(diff, ArtifactDiff):
            return
        self._selected_paths.discard(diff.path)
        self._manual_diffs = [
            item for item in self._manual_diffs if item.path != diff.path
        ]
        self._populate_diff_table()

    def _clear_send_queue(self):
        self._selected_paths.clear()
        self._manual_diffs.clear()
        self._populate_diff_table()

    def _filter_send_table(self, text):
        query = text.strip().lower()
        for row in range(self.diff_table.rowCount()):
            item = self.diff_table.item(row, 1)
            self.diff_table.setRowHidden(
                row, bool(query and item and query not in item.text().lower())
            )

    def _filter_receive_queue(self, mode):
        for row in range(self.receive_queue.rowCount()):
            status_item = self.receive_queue.item(row, 3)
            status = status_item.text() if status_item else ""
            visible = (
                mode == "all"
                or (mode == "active" and "传输中" in status)
                or (mode == "done" and "完成" in status)
            )
            self.receive_queue.setRowHidden(row, not visible)

    def set_dir_a(self, folder_path):
        self.folder_sync_panel.set_dir_a(folder_path)
        if not self.receive_dir_input.text().strip():
            self.receive_dir_input.setText(str(Path(folder_path) / "Echovault接收"))
        if not self.config.transfer.outbox_dir:
            outbox = Path(folder_path) / "Echovault输出" / "待回传"
            self.config.transfer.outbox_dir = str(outbox)
            self.session_manager.outbox_dir = outbox
            self.outbox_path_label.setText(str(outbox))
            config_manager.config = self.config
            config_manager.save()

    def refresh_transfer_results(self):
        """Reload phone sessions so newly registered processing outputs appear."""
        session_id = (
            self._current_session.session_id if self._current_session is not None else None
        )
        self._refresh_sessions(session_id)

    def _browse_receive_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择手机文件接收目录")
        if directory:
            self.receive_dir_input.setText(directory)
            self.config.transfer.receive_dir = directory
            config_manager.config = self.config
            config_manager.save()

    def _open_receive_dir(self):
        directory = self.receive_dir_input.text().strip()
        if not directory:
            QMessageBox.information(self, "打开接收目录", "请先选择接收目录。")
            return
        path = Path(directory)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "打开接收目录", f"无法创建接收目录：{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _toggle_receiver(self, checked):
        if checked:
            root = self.receive_dir_input.text().strip()
            if not root:
                self.receiver_button.setChecked(False)
                QMessageBox.warning(self, "提示", "请先选择接收目录。")
                return
            try:
                Path(root).mkdir(parents=True, exist_ok=True)
                self._localsend = LocalSendReceiver(
                    root,
                    self.config.transfer.device_alias,
                    on_file_received=self._file_received.emit,
                    on_progress=lambda current, total, name: self._receive_progress.emit(
                        current, total, name
                    ),
                    on_device_discovered=self._device_discovered.emit,
                    on_session_completed=self._session_completed.emit,
                )
                self._localsend.start()
            except Exception as exc:
                self._localsend = None
                self.receiver_button.setChecked(False)
                QMessageBox.critical(self, "无法开启手机接收", str(exc))
                return
            self.config.transfer.receive_dir = root
            config_manager.config = self.config
            config_manager.save()
            self.receiver_button.setText("停止接收")
            self.receiver_status.setText(f"● 正在接收 · 端口 {HTTP_PORT}")
            self.receiver_status.setStyleSheet("color:#2F9B63;font-weight:700")
            self._refresh_devices()
        else:
            if self._localsend:
                self._localsend.stop()
                self._localsend = None
            self.receiver_button.setText("开启接收")
            self.receiver_status.setText("● 未开启")
            self.receiver_status.setStyleSheet("")

    def _on_receive_progress_ui(self, current, total, name):
        self.receive_progress.setVisible(True)
        self.receive_progress.setMaximum(max(1, total))
        self.receive_progress.setValue(current)
        self.receiver_status.setText(f"正在接收：{name}")
        row = 0
        if self.receive_queue.rowCount() == 0:
            self.receive_queue.insertRow(0)
        self.receive_queue.setItem(row, 0, QTableWidgetItem(name))
        self.receive_queue.setItem(row, 1, QTableWidgetItem("局域网设备"))
        percent = int(current / max(total, 1) * 100)
        self.receive_queue.setItem(row, 2, QTableWidgetItem(f"{percent}%"))
        self.receive_queue.setItem(row, 3, QTableWidgetItem("传输中"))

    def _on_file_received_ui(self, path):
        self.recent_received.setText(f"最近接收：{Path(path).name}")
        self.recent_received.setVisible(True)
        row = 0
        if self.receive_queue.rowCount() == 0:
            self.receive_queue.insertRow(0)
        self.receive_queue.setItem(row, 0, QTableWidgetItem(Path(path).name))
        self.receive_queue.setItem(row, 1, QTableWidgetItem("局域网设备"))
        self.receive_queue.setItem(row, 2, QTableWidgetItem("100%"))
        self.receive_queue.setItem(row, 3, QTableWidgetItem("已完成 ✓"))

    def _on_session_completed_ui(self, payload):
        self.receive_progress.setVisible(False)
        self.receiver_status.setText("接收完成，正在建立原始文件清单…")
        self.index_worker = SessionIndexWorker(self.session_manager, payload, self)
        self.index_worker.finished.connect(self._session_indexed)
        self.index_worker.failed.connect(
            lambda error: QMessageBox.warning(self, "任务清单建立失败", error)
        )
        self.index_worker.start()

    def _session_indexed(self, session_id):
        self.receiver_status.setText(f"等待手机 · 端口 {HTTP_PORT}")
        self._refresh_sessions(session_id)

    def _refresh_sessions(self, select_id=None):
        current_id = select_id or self.session_combo.currentData()
        self._sessions = self.session_manager.list_sessions()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        selected_index = -1
        for index, session in enumerate(self._sessions):
            sender = session.sender.get("alias", "未知设备")
            time_text = session.received_at.replace("T", " ")[:16]
            self.session_combo.addItem(
                f"{time_text} · {sender} · {len(session.original_files)} 个文件",
                session.session_id,
            )
            if session.session_id == current_id:
                selected_index = index
        self.session_combo.blockSignals(False)
        if self._sessions:
            self.session_combo.setCurrentIndex(max(0, selected_index))
            self._load_selected_session()
        else:
            self._current_session = None
            self._diffs = []
            self.diff_table.setRowCount(0)
            self.task_status.setText("当前没有处理任务，可使用右上角按钮添加文件")

    def _load_selected_session(self):
        session_id = self.session_combo.currentData()
        if not session_id:
            return
        try:
            self._current_session = self.session_manager.load(session_id)
        except Exception as exc:
            QMessageBox.warning(self, "无法读取传输任务", str(exc))
            return
        self._scan_current_session()

    def _scan_current_session(self):
        if self._current_session is None:
            return
        if hasattr(self, "diff_worker") and self.diff_worker.isRunning():
            return
        try:
            session = self.session_manager.load(self._current_session.session_id)
        except Exception as exc:
            QMessageBox.warning(self, "无法读取传输任务", str(exc))
            return
        self.task_status.setText("正在核对接收基线和处理结果…")
        self.diff_worker = DiffScanWorker(
            session, self.config.transfer.strict_hash, self
        )
        self.diff_worker.finished.connect(self._diff_scan_finished)
        self.diff_worker.failed.connect(
            lambda error: QMessageBox.warning(self, "差异扫描失败", error)
        )
        self.diff_worker.start()

    def _diff_scan_finished(self, session, diffs):
        self._current_session = session
        self._diffs = diffs
        if self._current_session.session_id not in self._selection_initialized:
            self._selected_paths.update(
                diff.path for diff in self._diffs if diff.recommended
            )
            self._selection_initialized.add(self._current_session.session_id)
        generated = sum(
            diff.status == "generated" and not diff.returned for diff in self._diffs
        )
        modified = sum(
            diff.status == "modified" and not diff.returned for diff in self._diffs
        )
        self.task_status.setText(
            f"原始文件 {len(self._current_session.original_files)} 个，"
            f"新生成 {generated} 个，已修改 {modified} 个。"
        )
        self._populate_diff_table()

    def _filtered_diffs(self):
        session_diffs = [
            diff
            for diff in self._diffs
            if not diff.returned and diff.status in {"generated", "modified"}
        ]
        known = {diff.path for diff in session_diffs}
        return session_diffs + [
            diff for diff in self._manual_diffs if diff.path not in known
        ]

    def _populate_diff_table(self):
        diffs = self._filtered_diffs()
        self.diff_table.blockSignals(True)
        self.diff_table.setRowCount(len(diffs))
        for row, diff in enumerate(diffs):
            choice = QTableWidgetItem()
            choice.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            choice.setCheckState(
                Qt.CheckState.Checked
                if diff.path in self._selected_paths
                else Qt.CheckState.Unchecked
            )
            choice.setData(Qt.ItemDataRole.UserRole, diff)
            self.diff_table.setItem(row, 0, choice)
            path = Path(diff.path)
            self.diff_table.setItem(row, 1, QTableWidgetItem(diff.relative_path))
            self.diff_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    OPERATION_TEXT.get(
                        diff.operation,
                        "手动添加" if diff.operation == "manual_import" else "处理结果",
                    )
                ),
            )
            self.diff_table.setItem(row, 3, QTableWidgetItem(path.suffix[1:].upper()))
            self.diff_table.setItem(row, 4, QTableWidgetItem(_format_size(diff.size)))
            self.diff_table.setItem(
                row, 5, QTableWidgetItem("已发送" if diff.returned else "就绪")
            )
        self.diff_table.blockSignals(False)
        self._update_selection_summary()

    def _selection_changed(self, item):
        if item.column() != 0:
            return
        diff = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(diff, ArtifactDiff):
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_paths.add(diff.path)
        else:
            self._selected_paths.discard(diff.path)
        self._update_selection_summary()

    def _select_all_diffs(self):
        self._selected_paths.update(diff.path for diff in self._filtered_diffs())
        self._populate_diff_table()

    def _clear_selection(self):
        self._selected_paths.clear()
        self._populate_diff_table()

    def _selected_files(self):
        return [
            diff.path
            for diff in self._filtered_diffs()
            if diff.path in self._selected_paths
            and diff.status != "missing"
            and Path(diff.path).is_file()
        ]

    def _update_selection_summary(self):
        paths = self._selected_files()
        size = sum(Path(path).stat().st_size for path in paths)
        self.selection_summary.setText(
            f"已选择 {len(paths)} 项 · {_format_size(size)}"
        )
        self.send_summary.setText(
            f"文件数量        {len(paths)} 个\n"
            f"总大小          {_format_size(size)}\n"
            f"目标设备        {self.device_combo.currentText() or '未选择'}"
        )
        self.send_button.setText(f"发送 {len(paths)} 个文件")
        device_ready = self.device_combo.currentData() in self._devices
        self.send_button.setEnabled(bool(paths) and device_ready)

    def _current_diff(self):
        row = self.diff_table.currentRow()
        if row < 0:
            return None
        item = self.diff_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _preview_selected(self):
        diff = self._current_diff()
        if isinstance(diff, ArtifactDiff) and Path(diff.path).is_file():
            ArtifactPreviewDialog(diff, self).exec()

    def _open_selected_file(self):
        diff = self._current_diff()
        if isinstance(diff, ArtifactDiff) and Path(diff.path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(diff.path))

    def _open_workspace(self):
        if self._current_session and Path(self._current_session.workspace).exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(self._current_session.workspace)
            )

    def _open_outbox(self):
        self.session_manager.outbox_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.session_manager.outbox_dir))
        )

    def _refresh_devices(self):
        if self._localsend:
            self._localsend._send_announcement()
            self.send_status.setText("正在发现同一局域网中的 LocalSend 设备…")
        else:
            self.send_status.setText("请先开启接收服务，再打开手机 LocalSend。")

    def _on_device_discovered_ui(self, payload):
        try:
            device = LocalSendDevice.from_payload(payload)
        except (TypeError, ValueError):
            return
        if not device.ip:
            return
        key = device.fingerprint or f"{device.ip}:{device.port}"
        self._devices[key] = device
        current_key = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        selected = -1
        for index, (device_key, discovered) in enumerate(self._devices.items()):
            self.device_combo.addItem(
                f"{discovered.alias} · {discovered.device_type} · {discovered.ip}",
                device_key,
            )
            if device_key == current_key:
                selected = index
        self.device_combo.blockSignals(False)
        self.device_combo.setCurrentIndex(max(0, selected))
        self.send_status.setText(f"已发现 {len(self._devices)} 台设备。")
        self._update_selection_summary()

    def _send_selected(self):
        files = self._selected_files()
        key = self.device_combo.currentData()
        device = self._devices.get(key)
        if not files or device is None:
            return
        total_size = sum(Path(path).stat().st_size for path in files)
        message = (
            f"将 {len(files)} 个文件（{_format_size(total_size)}）发送到 "
            f"{device.alias}。\n\n手机上的保存位置由 LocalSend 设置决定，继续吗？"
        )
        if QMessageBox.question(self, "确认回传", message) != (
            QMessageBox.StandardButton.Yes
        ):
            return
        self.send_worker = SendWorker(
            LocalSendSender(self.config.transfer.device_alias), device, files, self
        )
        self.send_worker.progress.connect(self._send_progress_changed)
        self.send_worker.finished.connect(
            lambda results: self._send_finished(device, results)
        )
        self.send_worker.failed.connect(self._send_failed)
        self.send_progress.setVisible(True)
        self.send_progress.setValue(0)
        self.cancel_send_button.setVisible(True)
        self.send_button.setEnabled(False)
        self.send_status.setText(f"正在发送到 {device.alias}…")
        self.send_worker.start()

    def _send_progress_changed(self, percent, filename):
        self.send_progress.setValue(percent)
        self.send_status.setText(f"正在发送：{filename} · {percent}%")

    def _cancel_send(self):
        if hasattr(self, "send_worker"):
            self.send_worker.cancel()

    def _send_finished(self, device, results):
        self.send_progress.setVisible(False)
        self.cancel_send_button.setVisible(False)
        if self._current_session is not None:
            self.session_manager.record_return(
                self._current_session, device=device.as_dict(), results=results
            )
        sent = sum(item.get("status") == "sent" for item in results)
        skipped = sum(item.get("status") == "skipped" for item in results)
        self.send_status.setText(f"回传完成：发送 {sent}，跳过 {skipped}。")
        if self._current_session is not None:
            self._scan_current_session()
        else:
            self._update_selection_summary()

    def _send_failed(self, error):
        self.send_progress.setVisible(False)
        self.cancel_send_button.setVisible(False)
        self.send_status.setText(f"发送失败：{error}")
        self._update_selection_summary()
        QMessageBox.warning(self, "发送失败", error)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"
