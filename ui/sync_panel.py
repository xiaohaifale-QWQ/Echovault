"""
同步面板 GUI

功能:
- 配置本地/远程文件夹路径
- 对比两个目录的差异
- 执行同步操作
- LocalSend 接收端 (手机 LocalSend App 直接发送文件到本机)
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
    QMessageBox, QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from core.sync_engine import (
    SyncEngine, SyncDirection, ConflictResolution,
    DiffType, FileDiff, SyncPlan,
)
from server.localsend_receiver import LocalSendReceiver


class SyncWorker(QThread):
    """后台执行同步"""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    
    def __init__(self, engine: SyncEngine, plan: SyncPlan, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.plan = plan
    
    def run(self):
        stats = self.engine.execute_plan(self.plan, self._on_progress)
        self.finished.emit(stats)
    
    def _on_progress(self, current: int, total: int, filename: str):
        self.progress.emit(current, total, filename)


class SyncPanel(QWidget):
    """同步面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = SyncEngine()
        self._diffs: list[FileDiff] = []
        self._plan: SyncPlan = None
        self._localsend: LocalSendReceiver = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        
        # 标题
        title = QLabel("文件同步")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        layout.addWidget(title)
        
        # 文件夹配置
        path_group = QGroupBox("同步路径")
        path_form = QFormLayout(path_group)
        
        # A: 本机
        a_layout = QHBoxLayout()
        self.dir_a_input = QLineEdit()
        self.dir_a_input.setPlaceholderText("电脑端音乐文件夹...")
        a_layout.addWidget(self.dir_a_input)
        btn_a = QPushButton("...")
        btn_a.setFixedWidth(36)
        btn_a.clicked.connect(lambda: self._browse_dir(self.dir_a_input))
        a_layout.addWidget(btn_a)
        path_form.addRow("本机 (A):", a_layout)
        
        # B: 远程
        b_layout = QHBoxLayout()
        self.dir_b_input = QLineEdit()
        self.dir_b_input.setPlaceholderText("手机端文件夹路径...")
        b_layout.addWidget(self.dir_b_input)
        btn_b = QPushButton("...")
        btn_b.setFixedWidth(36)
        btn_b.clicked.connect(lambda: self._browse_dir(self.dir_b_input))
        b_layout.addWidget(btn_b)
        path_form.addRow("手机 (B):", b_layout)
        
        layout.addWidget(path_group)
        
        # 同步设置
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("方向:"))
        
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("双向合并", SyncDirection.BIDIRECTIONAL.value)
        self.direction_combo.addItem("A -> B (电脑到手机)", SyncDirection.A_TO_B.value)
        self.direction_combo.addItem("B -> A (手机到电脑)", SyncDirection.B_TO_A.value)
        self.direction_combo.addItem("镜像 A->B (完全覆盖)", SyncDirection.MIRROR_A_TO_B.value)
        settings_layout.addWidget(self.direction_combo)
        
        settings_layout.addSpacing(20)
        settings_layout.addWidget(QLabel("冲突:"))
        
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("手动选择", ConflictResolution.MANUAL.value)
        self.conflict_combo.addItem("自动选最新", ConflictResolution.NEWEST.value)
        self.conflict_combo.addItem("跳过", ConflictResolution.SKIP.value)
        settings_layout.addWidget(self.conflict_combo)
        
        settings_layout.addStretch()
        layout.addLayout(settings_layout)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.btn_compare = QPushButton("对比")
        self.btn_compare.setMinimumHeight(36)
        self.btn_compare.setStyleSheet("background: #1976D2; color: white; border-radius: 4px; font-weight: bold;")
        self.btn_compare.clicked.connect(self._on_compare)
        btn_layout.addWidget(self.btn_compare)
        
        self.btn_sync = QPushButton("执行同步")
        self.btn_sync.setMinimumHeight(36)
        self.btn_sync.setEnabled(False)
        self.btn_sync.clicked.connect(self._on_sync)
        btn_layout.addWidget(self.btn_sync)
        
        layout.addLayout(btn_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 差异列表
        diff_group = QGroupBox("差异文件")
        diff_layout = QVBoxLayout(diff_group)
        
        self.diff_table = QTableWidget()
        self.diff_table.setColumnCount(3)
        self.diff_table.setHorizontalHeaderLabels(["文件", "差异类型", "大小"])
        header = self.diff_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.diff_table.setColumnWidth(1, 120)
        self.diff_table.setColumnWidth(2, 80)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        
        diff_layout.addWidget(self.diff_table)
        
        self.diff_summary = QLabel("")
        diff_layout.addWidget(self.diff_summary)
        
        layout.addWidget(diff_group)
        
        # LocalSend 接收端
        ls_group = QGroupBox("LocalSend 接收")
        ls_layout = QVBoxLayout(ls_group)
        
        ls_desc = QLabel(
            "开启后，本机在局域网中显示为 LocalSend 设备。\n"
            "手机打开 LocalSend App 即可发现本机并发送文件到 A 路径。"
        )
        ls_desc.setStyleSheet("color: #666; font-size: 12px; padding: 4px;")
        ls_desc.setWordWrap(True)
        ls_layout.addWidget(ls_desc)
        
        ls_btn_layout = QHBoxLayout()
        
        self.btn_localsend = QPushButton("开启 LocalSend 接收")
        self.btn_localsend.setMinimumHeight(36)
        self.btn_localsend.setCheckable(True)
        self.btn_localsend.toggled.connect(self._on_toggle_localsend)
        ls_btn_layout.addWidget(self.btn_localsend)
        
        self.ls_status = QLabel("未启动")
        self.ls_status.setStyleSheet("color: #999;")
        ls_btn_layout.addWidget(self.ls_status)
        ls_btn_layout.addStretch()
        
        ls_layout.addLayout(ls_btn_layout)
        
        self.ls_recent = QLabel("")
        self.ls_recent.setStyleSheet("color: #4CAF50; font-size: 11px;")
        self.ls_recent.setWordWrap(True)
        ls_layout.addWidget(self.ls_recent)
        
        layout.addWidget(ls_group)
        layout.addStretch()
    
    def set_dir_a(self, path: str):
        """设置本机目录"""
        self.dir_a_input.setText(path)
    
    # ─── 事件处理 ──────────────────────
    
    def _browse_dir(self, line_edit: QLineEdit):
        dir_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if dir_path:
            line_edit.setText(dir_path)
    
    def _on_compare(self):
        dir_a = self.dir_a_input.text().strip()
        dir_b = self.dir_b_input.text().strip()
        
        if not dir_a or not dir_b:
            QMessageBox.warning(self, "提示", "请先配置两个同步路径。")
            return
        
        self.diff_table.setRowCount(0)
        self.diff_summary.setText("对比中...")
        
        try:
            self._diffs = self.engine.compare_directories(dir_a, dir_b)
            self._populate_diff_table()
            
            only_a = sum(1 for d in self._diffs if d.diff_type == DiffType.ONLY_IN_A)
            only_b = sum(1 for d in self._diffs if d.diff_type == DiffType.ONLY_IN_B)
            newer = sum(1 for d in self._diffs if d.diff_type in (DiffType.NEWER_IN_A, DiffType.NEWER_IN_B))
            conflicts = sum(1 for d in self._diffs if d.diff_type == DiffType.CONFLICT)
            
            self.diff_summary.setText(
                f"共 {len(self._diffs)} 个差异 | "
                f"仅A: {only_a} | 仅B: {only_b} | 更新: {newer} | 冲突: {conflicts}"
            )
            
            self.btn_sync.setEnabled(len(self._diffs) > 0)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"对比失败: {e}")
    
    def _populate_diff_table(self):
        self.diff_table.setRowCount(len(self._diffs))
        
        type_labels = {
            DiffType.ONLY_IN_A: "仅在电脑",
            DiffType.ONLY_IN_B: "仅在手机",
            DiffType.NEWER_IN_A: "电脑较新",
            DiffType.NEWER_IN_B: "手机较新",
            DiffType.CONFLICT: "冲突",
        }
        
        for row, diff in enumerate(self._diffs):
            self.diff_table.setItem(row, 0, QTableWidgetItem(diff.file.relative_path))
            self.diff_table.setItem(row, 1, QTableWidgetItem(
                type_labels.get(diff.diff_type, diff.diff_type.value)
            ))
            size_str = f"{diff.file.size / 1024:.0f} KB" if diff.file.size > 1024 else f"{diff.file.size} B"
            self.diff_table.setItem(row, 2, QTableWidgetItem(size_str))
    
    def _on_sync(self):
        dir_a = self.dir_a_input.text().strip()
        dir_b = self.dir_b_input.text().strip()
        
        if not self._diffs:
            return
        
        direction_str = self.direction_combo.currentData()
        direction = SyncDirection(direction_str)
        
        conflict_str = self.conflict_combo.currentData()
        self.engine.conflict_resolution = ConflictResolution(conflict_str)
        
        self._plan = self.engine.create_plan(self._diffs, direction, dir_a, dir_b)
        
        if self._plan.is_empty:
            QMessageBox.information(self, "提示", "没有需要同步的文件。")
            return
        
        reply = QMessageBox.question(
            self, "确认同步",
            f"将执行 {self._plan.total_operations} 个操作:\n"
            f"- 复制文件: {len(self._plan.files_to_copy)} 个\n"
            f"- 删除文件: {len(self._plan.files_to_delete)} 个\n"
            f"- 冲突文件: {len(self._plan.files_with_conflict)} 个\n\n"
            f"是否继续？",
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.worker = SyncWorker(self.engine, self._plan)
        self.worker.progress.connect(self._on_sync_progress)
        self.worker.finished.connect(self._on_sync_finished)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(self._plan.total_operations)
        self.progress_bar.setValue(0)
        self.btn_sync.setEnabled(False)
        
        self.worker.start()
    
    def _on_sync_progress(self, current: int, total: int, filename: str):
        self.progress_bar.setValue(current)
    
    def _on_sync_finished(self, stats: dict):
        self.progress_bar.setVisible(False)
        self.btn_sync.setEnabled(True)
        
        QMessageBox.information(
            self, "同步完成",
            f"复制: {stats['copied']} | 删除: {stats['deleted']} | "
            f"跳过: {stats['skipped']} | 错误: {stats['errors']}"
        )
    
    # ─── LocalSend 接收端 ──────────────
    
    def _on_toggle_localsend(self, checked: bool):
        if checked:
            dir_a = self.dir_a_input.text().strip()
            if not dir_a:
                QMessageBox.warning(self, "提示", "请先配置本机文件夹路径 (A)。")
                self.btn_localsend.setChecked(False)
                return
            
            self._start_localsend(dir_a)
        else:
            self._stop_localsend()
    
    def _start_localsend(self, save_dir: str):
        self._localsend = LocalSendReceiver(
            save_dir=save_dir,
            alias="MusicSync",
            on_file_received=self._on_file_received,
        )
        self._localsend.start()
        
        from server.localsend_receiver import HTTP_PORT
        ip = self._localsend._get_local_ip()
        
        self.btn_localsend.setText("关闭 LocalSend 接收")
        self.ls_status.setText(f"运行中 - 端口 {HTTP_PORT}")
        self.ls_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        
        QMessageBox.information(
            self, "LocalSend 已启动",
            f"本机已作为 LocalSend 设备运行。\n\n"
            f"设备名: MusicSync\n"
            f"地址: {ip}:{HTTP_PORT}\n\n"
            f"请在手机 LocalSend App 中查找 'MusicSync' 设备，\n"
            f"选择音乐文件发送即可。文件将保存到:\n"
            f"{save_dir}"
        )
    
    def _stop_localsend(self):
        if self._localsend:
            self._localsend.stop()
            self._localsend = None
        
        self.btn_localsend.setText("开启 LocalSend 接收")
        self.ls_status.setText("未启动")
        self.ls_status.setStyleSheet("color: #999;")
    
    def _on_file_received(self, file_path: str):
        """LocalSend 收到文件的回调"""
        name = Path(file_path).name
        self.ls_recent.setText(f"最近接收: {name}")
