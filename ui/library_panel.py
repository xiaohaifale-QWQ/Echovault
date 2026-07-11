"""
音乐库面板 — 左侧文件夹树
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QHBoxLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal


class LibraryPanel(QWidget):
    
    folder_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_path = ""
        self._collapsed = False
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        
        # 标题栏（始终可见）
        header = QHBoxLayout()
        title = QLabel("音乐库")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        header.addWidget(title)
        header.addStretch()
        
        self.btn_collapse = QPushButton("\u00AB")
        self.btn_collapse.setFixedSize(22, 22)
        self.btn_collapse.setToolTip("收起/展开音乐库")
        self.btn_collapse.setStyleSheet("QPushButton { border: none; font-size: 12px; color: #888; } QPushButton:hover { color: #333; }")
        self.btn_collapse.clicked.connect(self._toggle_collapse)
        header.addWidget(self.btn_collapse)
        layout.addLayout(header)
        
        # 文件夹树 + 提示（可折叠部分）
        from PyQt6.QtWidgets import QFrame
        self._collapse_container = QFrame()
        cl = QVBoxLayout(self._collapse_container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemExpanded.connect(self._on_expanded)
        cl.addWidget(self.tree)
        
        hint = QLabel("点击文件夹加载歌曲\nCtrl+O 打开新文件夹")
        hint.setStyleSheet("color: #888; font-size: 11px; padding: 4px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(hint)
        
        layout.addWidget(self._collapse_container)
    
    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._collapse_container.setVisible(not self._collapsed)
        self.btn_collapse.setText("\u00BB" if self._collapsed else "\u00AB")
    
    def set_root(self, folder_path: str):
        """设置根目录"""
        if not os.path.isdir(folder_path):
            return
        
        self._root_path = folder_path
        self.tree.clear()
        
        root_item = QTreeWidgetItem([os.path.basename(folder_path) or folder_path])
        root_item.setData(0, Qt.ItemDataRole.UserRole, folder_path)
        root_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        
        self.tree.addTopLevelItem(root_item)
        self._populate_children(root_item, folder_path)
        root_item.setExpanded(True)
        
        # 默认选中根目录
        self.tree.setCurrentItem(root_item)
        self.folder_selected.emit(folder_path)
    
    def _populate_children(self, parent_item: QTreeWidgetItem, folder_path: str, max_depth: int = 1):
        """填充子文件夹"""
        if max_depth <= 0:
            return
        
        try:
            entries = sorted(os.scandir(folder_path), key=lambda e: e.name.lower())
        except PermissionError:
            return
        
        for entry in entries:
            if entry.is_dir() and not entry.name.startswith("."):
                child = QTreeWidgetItem([entry.name])
                child.setData(0, Qt.ItemDataRole.UserRole, entry.path)
                
                # 检查是否有子文件夹
                try:
                    has_subdirs = any(
                        e.is_dir() and not e.name.startswith(".")
                        for e in os.scandir(entry.path)
                    )
                except PermissionError:
                    has_subdirs = False
                
                if has_subdirs:
                    child.setChildIndicatorPolicy(
                        QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                    )
                    # 添加占位节点以便展开
                    placeholder = QTreeWidgetItem(["..."])
                    child.addChild(placeholder)
                
                parent_item.addChild(child)
    
    def _on_expanded(self, item: QTreeWidgetItem):
        """展开节点时加载子文件夹"""
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_path:
            return
        
        # 移除占位节点并加载真正的子文件夹
        while item.childCount() > 0:
            child = item.child(0)
            if child.text(0) == "...":
                item.removeChild(child)
            else:
                break  # 已经加载过了
        
        if item.childCount() == 0:
            self._populate_children(item, folder_path, max_depth=1)
    
    def _on_clicked(self, item: QTreeWidgetItem, column: int):
        """点击文件夹"""
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if folder_path and os.path.isdir(folder_path):
            self.folder_selected.emit(folder_path)
