"""Song list panel with filter + format column"""
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QLineEdit, QHBoxLayout, QAbstractItemView, QComboBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush

COLOR_HAS_LRC = QColor(76, 175, 80)

def _fmt_size(b): return f"{b/1024:.0f}KB" if b>1024 else f"{b}B"

class SongListPanel(QWidget):
    song_selected = pyqtSignal(dict)
    model_updated = pyqtSignal()
    COL_NAME, COL_FORMAT, COL_STATUS, COL_SIZE, COL_FOLDER, COL_PATH = 0, 1, 2, 3, 4, 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs = []; self._filter_type = "all"; self._setup_ui()

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(4,4,4,4)
        h = QHBoxLayout()
        t = QLabel("歌曲列表"); t.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        h.addWidget(t); h.addStretch()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("搜索...")
        self.search_box.setClearButtonEnabled(True); self.search_box.setMaximumWidth(150)
        self.search_box.textChanged.connect(self._do_refresh); h.addWidget(self.search_box)
        self.filter_combo = QComboBox(); self.filter_combo.addItems(["全部","有歌词","无歌词"])
        self.filter_combo.setMaximumWidth(80); self.filter_combo.currentIndexChanged.connect(self._on_filter); h.addWidget(self.filter_combo)
        l.addLayout(h)
        self.table = QTableWidget(); self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["歌曲名称","格式","状态","大小","文件夹","路径"])
        self.table.setColumnHidden(self.COL_PATH, True)
        hv = self.table.horizontalHeader()
        hv.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        [hv.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed) for c in [1,2,3,4]]
        self.table.setColumnWidth(1,50); self.table.setColumnWidth(2,50); self.table.setColumnWidth(3,60); self.table.setColumnWidth(4,100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_sel); l.addWidget(self.table)

    def load_songs(self, songs): self._songs = songs; self._do_refresh()

    def _do_refresh(self, *a):
        self.table.setRowCount(0); f = self._songs
        t = self.search_box.text().lower()
        if t: f = [s for s in f if t in s["name"].lower()]
        if self._filter_type == "has_lrc": f = [s for s in f if s.get("has_lrc")]
        elif self._filter_type == "no_lrc": f = [s for s in f if not s.get("has_lrc")]
        self.table.setRowCount(len(f))
        for i, s in enumerate(f):
            n = QTableWidgetItem(s["name"]); n.setData(Qt.ItemDataRole.UserRole, s); self.table.setItem(i, 0, n)
            fmt = Path(s["name"]).suffix.lstrip(".").upper()
            fi = QTableWidgetItem(fmt); fi.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.table.setItem(i, 1, fi)
            st = "OK" if s.get("has_lrc") else "--"
            si = QTableWidgetItem(st); si.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if s.get("has_lrc"): si.setForeground(QBrush(COLOR_HAS_LRC))
            self.table.setItem(i, 2, si)
            zi = QTableWidgetItem(_fmt_size(s.get("size",0)))
            zi.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); self.table.setItem(i, 3, zi)
            self.table.setItem(i, 4, QTableWidgetItem(s.get("folder","")))
            self.table.setItem(i, 5, QTableWidgetItem(s.get("path","")))
        self.model_updated.emit()

    def _on_filter(self, idx):
        types = ["all","has_lrc","no_lrc"]; self._filter_type = types[idx] if idx < len(types) else "all"; self._do_refresh()

    def _on_sel(self):
        sel = self.get_selected_songs()
        if sel: self.song_selected.emit(sel[0])

    def get_selected_songs(self):
        s = []; 
        for i in self.table.selectedItems():
            d = i.data(Qt.ItemDataRole.UserRole)
            if d and d not in s: s.append(d)
        return s

    def get_all_songs(self): return self._songs.copy()

    def update_song_status(self, fp, ok):
        for s in self._songs:
            if s["path"] == fp: s["has_lrc"] = ok; break
        self._do_refresh()
        sel = self.get_selected_songs()
        if sel: self.song_selected.emit(sel[0])
