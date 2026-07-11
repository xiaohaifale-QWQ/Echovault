"""
同步面板 GUI

功能:
- 配置本地/远程文件夹路径
- 对比两个目录的差异
- 显示差异列表
- 执行同步操作
- 启动 HTTP 文件服务
- 启动 mDNS 设备发现
"""

import os
import asyncio
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
    QMessageBox, QProgressBar, QTextEdit, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from core.sync_engine import (
    SyncEngine, SyncDirection, ConflictResolution,
    DiffType, FileDiff, SyncPlan,
)
from server.http_server import SyncHTTPServer
from server.discovery import DiscoveryService, get_local_ip


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
        self._http_server: SyncHTTPServer = None
        self._discovery: DiscoveryService = None
        self._server_thread: threading.Thread = None
        
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
        a_layout_btn = btn_b  # keep reference
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
        
        self.btn_server = QPushButton("启动服务")
        self.btn_server.setMinimumHeight(36)
        self.btn_server.setCheckable(True)
        self.btn_server.toggled.connect(self._on_toggle_server)
        btn_layout.addWidget(self.btn_server)
        
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
        
        # 设备发现
        disc_group = QGroupBox("局域网设备")
        disc_layout = QVBoxLayout(disc_group)
        
        self.device_label = QLabel("未扫描")
        self.device_label.setStyleSheet("color: #666;")
        disc_layout.addWidget(self.device_label)
        
        self.btn_discover = QPushButton("扫描设备")
        self.btn_discover.clicked.connect(self._on_discover)
        disc_layout.addWidget(self.btn_discover)
        
        layout.addWidget(disc_group)
    
    def set_dir_a(self, path: str):
        """设置本机目录"""
        self.dir_a_input.setText(path)
    
    # ─── 事件处理 ──────────────────────
    
    def _browse_dir(self, line_edit: QLineEdit):
        """选择文件夹"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if dir_path:
            line_edit.setText(dir_path)
    
    def _on_compare(self):
        """对比两个目录"""
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
            
            # 统计
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
        """填充差异表格"""
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
        """执行同步"""
        dir_a = self.dir_a_input.text().strip()
        dir_b = self.dir_b_input.text().strip()
        
        if not self._diffs:
            return
        
        # 生成计划
        direction_str = self.direction_combo.currentData()
        direction = SyncDirection(direction_str)
        
        conflict_str = self.conflict_combo.currentData()
        self.engine.conflict_resolution = ConflictResolution(conflict_str)
        
        self._plan = self.engine.create_plan(self._diffs, direction, dir_a, dir_b)
        
        if self._plan.is_empty:
            QMessageBox.information(self, "提示", "没有需要同步的文件。")
            return
        
        # 确认
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
        
        # 后台执行
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
    
    def _on_toggle_server(self, checked: bool):
        """启动/停止 HTTP 文件服务"""
        if checked:
            dir_a = self.dir_a_input.text().strip()
            if not dir_a:
                QMessageBox.warning(self, "提示", "请先配置本机文件夹路径。")
                self.btn_server.setChecked(False)
                return
            
            self._start_http_server(dir_a)
        else:
            self._stop_http_server()
    
    def _start_http_server(self, music_dir: str):
        """在后台线程启动 HTTP 服务"""
        self._http_server = SyncHTTPServer(music_dir)
        
        async def _run():
            await self._http_server.start()
        
        def _thread_run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.run_forever()
        
        self._server_thread = threading.Thread(target=_thread_run, daemon=True)
        self._server_thread.start()
        
        ip = get_local_ip()
        self.btn_server.setText("停止服务")
        QMessageBox.information(
            self, "服务已启动",
            f"HTTP 文件服务已启动\n\n"
            f"本机地址: http://{ip}:{SyncHTTPServer.DEFAULT_PORT}\n\n"
            f"手机浏览器打开此地址即可访问文件。"
        )
        
        # 同时启动 mDNS 广播
        self._discovery = DiscoveryService(SyncHTTPServer.DEFAULT_PORT)
        self._discovery.start_advertising()
    
    def _stop_http_server(self):
        """停止 HTTP 服务"""
        if self._discovery:
            self._discovery.stop()
        
        # aiohttp 没有同步的 stop 方法，依赖线程 daemon
        self.btn_server.setText("启动服务")
    
    def _on_discover(self):
        """扫描局域网设备"""
        if not self._discovery:
            self._discovery = DiscoveryService()
        
        if not self._discovery.is_available:
            QMessageBox.warning(self, "提示", "zeroconf 未安装，无法扫描设备。\npip install zeroconf")
            return
        
        self._discovery.start_discovery(self._on_device_found)
        self.device_label.setText("扫描中...")
    
    def _on_device_found(self, device: dict):
        """发现设备回调"""
        devices = self._discovery.get_discovered_devices()
        text = "\n".join(
            f"  {d['name']} — http://{d['ip']}:{d['port']}"
            for d in devices
        )
        self.device_label.setText(f"已发现 {len(devices)} 个设备:\n{text}")
