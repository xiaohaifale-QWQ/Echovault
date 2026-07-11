"""
同步面板 GUI - LocalSend 接收 + 文件同步
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
from core.config import config_manager
from server.localsend_receiver import LocalSendReceiver


class SyncWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    
    def __init__(self, engine: SyncEngine, plan: SyncPlan, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.plan = plan
    
    def run(self):
        stats = self.engine.execute_plan(self.plan, self._on_progress)
        self.finished.emit(stats)
    
    def _on_progress(self, current, total, filename):
        self.progress.emit(current, total, filename)


class SyncPanel(QWidget):
    # 线程安全信号：HTTP 线程 -> 主线程
    _ls_progress = pyqtSignal(int, int, str)
    _ls_received = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = SyncEngine()
        self._diffs = []
        self._plan = None
        self._localsend = None
        
        self._setup_ui()
        
        # 连接线程安全信号
        self._ls_progress.connect(self._on_ls_progress_ui)
        self._ls_received.connect(self._on_ls_received_ui)
        
        # 加载上次路径
        cfg = config_manager.load()
        if cfg.sync.remote_dir:
            self.dir_b_input.setText(cfg.sync.remote_dir)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        
        title = QLabel("文件同步")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        layout.addWidget(title)
        
        # 路径配置
        pg = QGroupBox("同步路径")
        pf = QFormLayout(pg)
        
        al = QHBoxLayout()
        self.dir_a_input = QLineEdit()
        self.dir_a_input.setPlaceholderText("电脑端音乐文件夹...")
        al.addWidget(self.dir_a_input)
        ba = QPushButton("..."); ba.setFixedWidth(36)
        ba.clicked.connect(lambda: self._browse(self.dir_a_input))
        al.addWidget(ba)
        pf.addRow("本机 (A):", al)
        
        bl = QHBoxLayout()
        self.dir_b_input = QLineEdit()
        self.dir_b_input.setPlaceholderText("手机端文件夹路径...")
        bl.addWidget(self.dir_b_input)
        bb = QPushButton("..."); bb.setFixedWidth(36)
        bb.clicked.connect(lambda: self._browse(self.dir_b_input))
        bl.addWidget(bb)
        pf.addRow("手机 (B):", bl)
        
        layout.addWidget(pg)
        
        # 同步设置
        sl = QHBoxLayout()
        sl.addWidget(QLabel("方向:"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("双向合并", SyncDirection.BIDIRECTIONAL.value)
        self.direction_combo.addItem("A -> B", SyncDirection.A_TO_B.value)
        self.direction_combo.addItem("B -> A", SyncDirection.B_TO_A.value)
        self.direction_combo.addItem("镜像 A->B", SyncDirection.MIRROR_A_TO_B.value)
        sl.addWidget(self.direction_combo)
        sl.addSpacing(20)
        sl.addWidget(QLabel("冲突:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("手动", ConflictResolution.MANUAL.value)
        self.conflict_combo.addItem("最新", ConflictResolution.NEWEST.value)
        self.conflict_combo.addItem("跳过", ConflictResolution.SKIP.value)
        sl.addWidget(self.conflict_combo)
        sl.addStretch()
        layout.addLayout(sl)
        
        # 按钮
        bl2 = QHBoxLayout()
        self.btn_compare = QPushButton("对比")
        self.btn_compare.setMinimumHeight(36)
        self.btn_compare.setStyleSheet("background: #1976D2; color: white; border-radius: 4px; font-weight: bold;")
        self.btn_compare.clicked.connect(self._on_compare)
        bl2.addWidget(self.btn_compare)
        self.btn_sync = QPushButton("执行同步")
        self.btn_sync.setMinimumHeight(36); self.btn_sync.setEnabled(False)
        self.btn_sync.clicked.connect(self._on_sync)
        bl2.addWidget(self.btn_sync)
        layout.addLayout(bl2)
        
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 差异表格
        dg = QGroupBox("差异文件")
        dl = QVBoxLayout(dg)
        self.diff_table = QTableWidget()
        self.diff_table.setColumnCount(3)
        self.diff_table.setHorizontalHeaderLabels(["文件", "差异类型", "大小"])
        h = self.diff_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.diff_table.setColumnWidth(1, 120); self.diff_table.setColumnWidth(2, 80)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        dl.addWidget(self.diff_table)
        self.diff_summary = QLabel(""); dl.addWidget(self.diff_summary)
        layout.addWidget(dg)
        
        # LocalSend
        lg = QGroupBox("LocalSend 接收")
        ll = QVBoxLayout(lg)
        ld = QLabel("开启后手机 LocalSend App 可发现本机并发送文件到 A 路径。")
        ld.setStyleSheet("color: #666; font-size: 12px; padding: 4px;"); ld.setWordWrap(True)
        ll.addWidget(ld)
        lb = QHBoxLayout()
        self.btn_localsend = QPushButton("开启 LocalSend 接收")
        self.btn_localsend.setMinimumHeight(36); self.btn_localsend.setCheckable(True)
        self.btn_localsend.toggled.connect(self._on_toggle_localsend)
        lb.addWidget(self.btn_localsend)
        self.ls_status = QLabel("未启动"); self.ls_status.setStyleSheet("color: #999;")
        lb.addWidget(self.ls_status); lb.addStretch()
        ll.addLayout(lb)
        self.ls_progress = QProgressBar(); self.ls_progress.setVisible(False)
        ll.addWidget(self.ls_progress)
        self.ls_recent = QLabel("")
        self.ls_recent.setStyleSheet("color: #4CAF50; font-size: 11px;"); self.ls_recent.setWordWrap(True)
        ll.addWidget(self.ls_recent)
        layout.addWidget(lg)
        layout.addStretch()
    
    def set_dir_a(self, path):
        self.dir_a_input.setText(path)
    
    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d: edit.setText(d)
    
    def _on_compare(self):
        a = self.dir_a_input.text().strip(); b = self.dir_b_input.text().strip()
        if not a or not b: return QMessageBox.warning(self, "提示", "请配置两个路径。")
        self.diff_table.setRowCount(0); self.diff_summary.setText("对比中...")
        try:
            self._diffs = self.engine.compare_directories(a, b)
            self._show_diffs()
            oa = sum(1 for d in self._diffs if d.diff_type == DiffType.ONLY_IN_A)
            ob = sum(1 for d in self._diffs if d.diff_type == DiffType.ONLY_IN_B)
            nw = sum(1 for d in self._diffs if d.diff_type in (DiffType.NEWER_IN_A, DiffType.NEWER_IN_B))
            cf = sum(1 for d in self._diffs if d.diff_type == DiffType.CONFLICT)
            self.diff_summary.setText(f"共 {len(self._diffs)} 差异 | 仅A:{oa} 仅B:{ob} 更新:{nw} 冲突:{cf}")
            self.btn_sync.setEnabled(len(self._diffs) > 0)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
    
    def _show_diffs(self):
        self.diff_table.setRowCount(len(self._diffs))
        tl = {DiffType.ONLY_IN_A:"仅在电脑", DiffType.ONLY_IN_B:"仅在手机",
              DiffType.NEWER_IN_A:"电脑较新", DiffType.NEWER_IN_B:"手机较新", DiffType.CONFLICT:"冲突"}
        for i, d in enumerate(self._diffs):
            self.diff_table.setItem(i, 0, QTableWidgetItem(d.file.relative_path))
            self.diff_table.setItem(i, 1, QTableWidgetItem(tl.get(d.diff_type, d.diff_type.value)))
            s = f"{d.file.size/1024:.0f}KB" if d.file.size > 1024 else f"{d.file.size}B"
            self.diff_table.setItem(i, 2, QTableWidgetItem(s))
    
    def _on_sync(self):
        a = self.dir_a_input.text().strip(); b = self.dir_b_input.text().strip()
        if not self._diffs: return
        d = SyncDirection(self.direction_combo.currentData())
        self.engine.conflict_resolution = ConflictResolution(self.conflict_combo.currentData())
        self._plan = self.engine.create_plan(self._diffs, d, a, b)
        if self._plan.is_empty: return QMessageBox.information(self, "提示", "无变化。")
        r = QMessageBox.question(self, "确认", f"{self._plan.total_operations} 个操作，继续？")
        if r != QMessageBox.StandardButton.Yes: return
        self.worker = SyncWorker(self.engine, self._plan)
        self.worker.progress.connect(self._on_sp)
        self.worker.finished.connect(self._on_sf)
        self.progress_bar.setVisible(True); self.progress_bar.setMaximum(self._plan.total_operations); self.progress_bar.setValue(0)
        self.btn_sync.setEnabled(False); self.worker.start()
    
    def _on_sp(self, c, t, f): self.progress_bar.setValue(c)
    def _on_sf(self, s):
        self.progress_bar.setVisible(False); self.btn_sync.setEnabled(True)
        QMessageBox.information(self, "完成", f"复制:{s['copied']} 删除:{s['deleted']} 跳过:{s['skipped']} 错误:{s['errors']}")
    
    # ─── LocalSend ─────────────────────────
    
    def _on_toggle_localsend(self, checked):
        if checked:
            a = self.dir_a_input.text().strip()
            if not a: self.btn_localsend.setChecked(False); return QMessageBox.warning(self, "提示", "请先配置 A 路径。")
            r = self.dir_b_input.text().strip()
            if r:
                c = config_manager.load(); c.sync.remote_dir = r; config_manager.save()
            self._start_ls(a)
        else:
            self._stop_ls()
    
    def _start_ls(self, d):
        self._localsend = LocalSendReceiver(d, "MusicSync",
            on_file_received=self._on_ls_file,
            on_progress=self._on_ls_prog)
        self._localsend.start()
        from server.localsend_receiver import HTTP_PORT
        ip = self._localsend._get_local_ip()
        self.btn_localsend.setText("关闭 LocalSend 接收")
        self.ls_status.setText(f"运行中 - 端口 {HTTP_PORT}")
        self.ls_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        QMessageBox.information(self, "LocalSend",
            f"设备名: MusicSync\n地址: {ip}:{HTTP_PORT} (HTTPS)\n\n手机 LocalSend 查找 'MusicSync' 即可发送。")
    
    def _stop_ls(self):
        if self._localsend: self._localsend.stop(); self._localsend = None
        self.btn_localsend.setText("开启 LocalSend 接收")
        self.ls_status.setText("未启动"); self.ls_status.setStyleSheet("color: #999;")
    
    def _on_ls_file(self, path):
        """HTTP 线程回调 -> 发射信号到主线程"""
        self._ls_received.emit(path)
    
    def _on_ls_prog(self, cur, tot, name):
        """HTTP 线程回调 -> 发射信号到主线程"""
        self._ls_progress.emit(cur, tot, name)
    
    def _on_ls_received_ui(self, path):
        """主线程: 更新接收状态"""
        self.ls_recent.setText(f"最近接收: {Path(path).name}")
        self.ls_progress.setVisible(False)
    
    def _on_ls_progress_ui(self, cur, tot, name):
        """主线程: 更新进度条"""
        self.ls_progress.setVisible(True)
        self.ls_progress.setMaximum(tot)
        self.ls_progress.setValue(cur)
        self.ls_status.setText(f"接收中: {name}")
