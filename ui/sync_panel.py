"""Phone transfer workspace with LocalSend receive, review, and return."""

from __future__ import annotations

import difflib
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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
    "vocal_separation": "人声分离",
    "audio_enhancement": "音频增强",
    "video_aggregation": "视频汇总",
}


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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("手机传输")
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 3px;")
        layout.addWidget(title)

        receive_group = QGroupBox("1. 从手机接收")
        receive_layout = QVBoxLayout(receive_group)
        path_row = QHBoxLayout()
        self.receive_dir_input = QLineEdit(self.config.transfer.receive_dir)
        self.receive_dir_input.setPlaceholderText("选择手机文件接收目录…")
        path_row.addWidget(QLabel("接收目录："))
        path_row.addWidget(self.receive_dir_input)
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_receive_dir)
        path_row.addWidget(browse)
        receive_layout.addLayout(path_row)
        service_row = QHBoxLayout()
        self.receiver_button = QPushButton("开启接收")
        self.receiver_button.setCheckable(True)
        self.receiver_button.clicked.connect(self._toggle_receiver)
        self.receiver_status = QLabel("未开启")
        service_row.addWidget(self.receiver_button)
        service_row.addWidget(self.receiver_status)
        service_row.addStretch()
        receive_layout.addLayout(service_row)
        self.receive_progress = QProgressBar()
        self.receive_progress.setVisible(False)
        receive_layout.addWidget(self.receive_progress)
        self.recent_received = QLabel("")
        receive_layout.addWidget(self.recent_received)
        layout.addWidget(receive_group)

        task_group = QGroupBox("2. 当前传输任务与处理结果")
        task_layout = QVBoxLayout(task_group)
        task_row = QHBoxLayout()
        self.session_combo = QComboBox()
        self.session_combo.currentIndexChanged.connect(self._load_selected_session)
        task_row.addWidget(QLabel("任务："))
        task_row.addWidget(self.session_combo, 1)
        refresh = QPushButton("刷新结果")
        refresh.clicked.connect(self._scan_current_session)
        task_row.addWidget(refresh)
        open_workspace = QPushButton("打开目录")
        open_workspace.clicked.connect(self._open_workspace)
        task_row.addWidget(open_workspace)
        task_layout.addLayout(task_row)
        outbox_row = QHBoxLayout()
        self.outbox_path_label = QLabel(str(self.session_manager.outbox_dir))
        self.outbox_path_label.setWordWrap(True)
        self.outbox_path_label.setStyleSheet("font-size:11px;color:#666")
        outbox_row.addWidget(QLabel("待回传目录："))
        outbox_row.addWidget(self.outbox_path_label, 1)
        open_outbox = QPushButton("打开待回传目录")
        open_outbox.clicked.connect(self._open_outbox)
        outbox_row.addWidget(open_outbox)
        task_layout.addLayout(outbox_row)
        self.task_status = QLabel("尚未收到手机文件")
        task_layout.addWidget(self.task_status)

        filters = QHBoxLayout()
        self.filter_combo = QComboBox()
        for text, value in [
            ("推荐回传", "recommended"),
            ("全部", "all"),
            ("新生成", "generated"),
            ("已修改", "modified"),
            ("原始文件", "unchanged"),
        ]:
            self.filter_combo.addItem(text, value)
        self.filter_combo.currentIndexChanged.connect(self._populate_diff_table)
        filters.addWidget(QLabel("显示："))
        filters.addWidget(self.filter_combo)
        select_recommended = QPushButton("全选推荐")
        select_recommended.clicked.connect(self._select_recommended)
        clear = QPushButton("清除选择")
        clear.clicked.connect(self._clear_selection)
        filters.addWidget(select_recommended)
        filters.addWidget(clear)
        filters.addStretch()
        task_layout.addLayout(filters)

        self.diff_table = QTableWidget(0, 6)
        self.diff_table.setHorizontalHeaderLabels(
            ["选择", "文件", "状态", "处理来源", "大小", "回传"]
        )
        header = self.diff_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.itemChanged.connect(self._selection_changed)
        self.diff_table.cellDoubleClicked.connect(lambda _row, _column: self._preview_selected())
        task_layout.addWidget(self.diff_table, 1)

        diff_actions = QHBoxLayout()
        preview = QPushButton("查看选中文件")
        preview.clicked.connect(self._preview_selected)
        open_file = QPushButton("打开文件")
        open_file.clicked.connect(self._open_selected_file)
        self.selection_summary = QLabel("已选择 0 个文件")
        diff_actions.addWidget(preview)
        diff_actions.addWidget(open_file)
        diff_actions.addStretch()
        diff_actions.addWidget(self.selection_summary)
        task_layout.addLayout(diff_actions)
        layout.addWidget(task_group, 1)

        send_group = QGroupBox("3. 把处理结果传回手机")
        send_layout = QVBoxLayout(send_group)
        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        device_row.addWidget(QLabel("发送到："))
        device_row.addWidget(self.device_combo, 1)
        discover = QPushButton("刷新设备")
        discover.clicked.connect(self._refresh_devices)
        device_row.addWidget(discover)
        send_layout.addLayout(device_row)
        action_row = QHBoxLayout()
        self.send_button = QPushButton("发送选中的文件到手机")
        self.send_button.setMinimumHeight(38)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._send_selected)
        self.cancel_send_button = QPushButton("取消")
        self.cancel_send_button.setVisible(False)
        self.cancel_send_button.clicked.connect(self._cancel_send)
        action_row.addWidget(self.send_button, 1)
        action_row.addWidget(self.cancel_send_button)
        send_layout.addLayout(action_row)
        self.send_progress = QProgressBar()
        self.send_progress.setVisible(False)
        send_layout.addWidget(self.send_progress)
        self.send_status = QLabel("请先开启接收，手机 LocalSend 打开后会出现在设备列表。")
        self.send_status.setWordWrap(True)
        send_layout.addWidget(self.send_status)
        layout.addWidget(send_group)

        self.advanced_group = QGroupBox("高级文件夹同步")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced_group)
        self.folder_sync_panel = FolderSyncPanel()
        self.folder_sync_panel.setVisible(False)
        self.advanced_group.toggled.connect(self.folder_sync_panel.setVisible)
        advanced_layout.addWidget(self.folder_sync_panel)
        layout.addWidget(self.advanced_group)

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

    def _browse_receive_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择手机文件接收目录")
        if directory:
            self.receive_dir_input.setText(directory)

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
            self.receiver_button.setText("关闭接收")
            self.receiver_status.setText(f"等待手机 · 端口 {HTTP_PORT}")
            self.receiver_status.setStyleSheet("color:#2e7d32;font-weight:bold")
            self._refresh_devices()
        else:
            if self._localsend:
                self._localsend.stop()
                self._localsend = None
            self.receiver_button.setText("开启接收")
            self.receiver_status.setText("未开启")
            self.receiver_status.setStyleSheet("")

    def _on_receive_progress_ui(self, current, total, name):
        self.receive_progress.setVisible(True)
        self.receive_progress.setMaximum(max(1, total))
        self.receive_progress.setValue(current)
        self.receiver_status.setText(f"正在接收：{name}")

    def _on_file_received_ui(self, path):
        self.recent_received.setText(f"最近接收：{Path(path).name}")

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
            self.task_status.setText("尚未收到手机文件")

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
        value = self.filter_combo.currentData()
        pending = [diff for diff in self._diffs if not diff.returned]
        if value == "all":
            return pending
        if value == "recommended":
            return [diff for diff in pending if diff.recommended]
        return [diff for diff in pending if diff.status == value]

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
            self.diff_table.setItem(row, 1, QTableWidgetItem(diff.relative_path))
            self.diff_table.setItem(
                row, 2, QTableWidgetItem(STATUS_TEXT.get(diff.status, diff.status))
            )
            self.diff_table.setItem(
                row,
                3,
                QTableWidgetItem(
                    OPERATION_TEXT.get(diff.operation, diff.operation or "自动扫描")
                ),
            )
            self.diff_table.setItem(row, 4, QTableWidgetItem(_format_size(diff.size)))
            self.diff_table.setItem(
                row, 5, QTableWidgetItem("已发送" if diff.returned else "未发送")
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

    def _select_recommended(self):
        self._selected_paths.update(diff.path for diff in self._diffs if diff.recommended)
        self._populate_diff_table()

    def _clear_selection(self):
        self._selected_paths.clear()
        self._populate_diff_table()

    def _selected_files(self):
        return [
            diff.path
            for diff in self._diffs
            if diff.path in self._selected_paths
            and diff.status != "missing"
            and Path(diff.path).is_file()
        ]

    def _update_selection_summary(self):
        paths = self._selected_files()
        size = sum(Path(path).stat().st_size for path in paths)
        self.selection_summary.setText(
            f"已选择 {len(paths)} 个文件，共 {_format_size(size)}"
        )
        self.send_button.setEnabled(bool(paths) and self.device_combo.count() > 0)

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
        if not files or device is None or self._current_session is None:
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
        self.session_manager.record_return(
            self._current_session, device=device.as_dict(), results=results
        )
        sent = sum(item.get("status") == "sent" for item in results)
        skipped = sum(item.get("status") == "skipped" for item in results)
        self.send_status.setText(f"回传完成：发送 {sent}，跳过 {skipped}。")
        self._scan_current_session()

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
