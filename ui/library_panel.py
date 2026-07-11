"""Music library folder tree (left panel)"""
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QHBoxLayout)
from PyQt6.QtCore import Qt, pyqtSignal

class LibraryPanel(QWidget):
    folder_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_path = ""
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4); layout.setSpacing(2)
        t = QLabel("音乐库"); t.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        layout.addWidget(t)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True); self.tree.setAnimated(True); self.tree.setIndentation(16)
        self.tree.itemClicked.connect(self._on_clicked); self.tree.itemExpanded.connect(self._on_expanded)
        layout.addWidget(self.tree)
        hint = QLabel("点击文件夹加载歌曲\nCtrl+O 打开新文件夹")
        hint.setStyleSheet("color:#888;font-size:11px;padding:4px")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(hint)
    
    def set_root(self, path):
        if not os.path.isdir(path): return
        self._root_path = path; self.tree.clear()
        root = QTreeWidgetItem([os.path.basename(path) or path])
        root.setData(0, Qt.ItemDataRole.UserRole, path)
        root.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        self.tree.addTopLevelItem(root); self._populate(root, path)
        root.setExpanded(True); self.tree.setCurrentItem(root); self.folder_selected.emit(path)
    
    def _populate(self, parent, path, depth=1):
        if depth <= 0: return
        try: entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        except: return
        for e in entries:
            if e.is_dir() and not e.name.startswith("."):
                c = QTreeWidgetItem([e.name]); c.setData(0, Qt.ItemDataRole.UserRole, e.path)
                try: has = any(d.is_dir() and not d.name.startswith(".") for d in os.scandir(e.path))
                except: has = False
                if has: c.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator); c.addChild(QTreeWidgetItem(["..."]))
                parent.addChild(c)
    
    def _on_expanded(self, item):
        p = item.data(0, Qt.ItemDataRole.UserRole)
        if not p: return
        while item.childCount() > 0 and item.child(0).text(0) == "...": item.removeChild(item.child(0))
        if item.childCount() == 0: self._populate(item, p)
    
    def _on_clicked(self, item, col):
        p = item.data(0, Qt.ItemDataRole.UserRole)
        if p and os.path.isdir(p): self.folder_selected.emit(p)
