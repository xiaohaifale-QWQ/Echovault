"""Song list with filters + inline rename"""
import os
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QLineEdit, QHBoxLayout, QAbstractItemView, QComboBox, QInputDialog, QMessageBox)
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
        self._songs = []; self._filter_type = "no_lrc"; self._setup_ui()
        self.filter_combo.setCurrentIndex(2)

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(4,4,4,4)
        h = QHBoxLayout()
        t = QLabel("歌曲列表"); t.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        h.addWidget(t); h.addStretch()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("搜索...")
        self.search_box.setClearButtonEnabled(True); self.search_box.setMaximumWidth(130)
        self.search_box.textChanged.connect(self._do_refresh); h.addWidget(self.search_box)
        self.filter_combo = QComboBox(); self.filter_combo.setMaximumWidth(90)
        self.filter_combo.currentIndexChanged.connect(self._on_filter); h.addWidget(self.filter_combo)
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
        self.table.itemSelectionChanged.connect(self._on_sel)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        l.addWidget(self.table)

    def _build_filter_items(self):
        formats = sorted(set(Path(s["name"]).suffix.upper() for s in self._songs))
        self.filter_combo.blockSignals(True)
        cur = self.filter_combo.currentText()
        self.filter_combo.clear()
        self.filter_combo.addItems(["全部","有歌词","无歌词"] + formats)
        idx = self.filter_combo.findText(cur)
        self.filter_combo.setCurrentIndex(idx if idx >= 0 else 2)
        self.filter_combo.blockSignals(False)

    def load_songs(self, songs):
        self._songs = songs; self._build_filter_items(); self._do_refresh()

    def _do_refresh(self, *a):
        self.table.setRowCount(0); f = self._songs
        t = self.search_box.text().lower()
        if t: f = [s for s in f if t in Path(s["name"]).stem.lower()]
        if self._filter_type == "has_lrc": f = [s for s in f if s.get("has_lrc")]
        elif self._filter_type == "no_lrc": f = [s for s in f if not s.get("has_lrc")]
        elif self._filter_type.startswith("."):
            fmt = self._filter_type.lstrip(".").upper()
            f = [s for s in f if Path(s["name"]).suffix.upper() == fmt]
        self.table.setRowCount(len(f))
        for i, s in enumerate(f):
            n = QTableWidgetItem(Path(s["name"]).stem); n.setData(Qt.ItemDataRole.UserRole, s); self.table.setItem(i, 0, n)
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
        txt = self.filter_combo.currentText()
        if txt == "全部": self._filter_type = "all"
        elif txt == "有歌词": self._filter_type = "has_lrc"
        elif txt == "无歌词": self._filter_type = "no_lrc"
        else: self._filter_type = txt.lower()
        self._do_refresh()

    def _on_sel(self):
        sel = self.get_selected_songs()
        if sel: self.song_selected.emit(sel[0])

    def _on_double_click(self, row, col):
        if col != self.COL_NAME: return
        item = self.table.item(row, 0)
        if not item: return
        song = item.data(Qt.ItemDataRole.UserRole)
        if not song: return
        old_path = Path(song["path"])
        
        from PyQt6.QtWidgets import QDialog, QVBoxLayout as VL, QDialogButtonBox as DBB
        dlg = QDialog(self); dlg.setWindowTitle("重命名")
        ll = VL(dlg); le = QLineEdit(old_path.stem); ll.addWidget(le)
        bb = DBB(DBB.StandardButton.Ok | DBB.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); ll.addWidget(bb)
        if not dlg.exec(): return
        new_stem = le.text().strip()
        if not new_stem or new_stem == old_path.stem: return
        
        new_name = new_stem + old_path.suffix
        new_path = old_path.parent / new_name
        old_str = str(old_path); new_str = str(new_path)
        try:
            os.rename(old_str, new_str)
            old_lrc = old_path.with_suffix(".lrc"); new_lrc = new_path.with_suffix(".lrc")
            if old_lrc.exists(): os.rename(str(old_lrc), str(new_lrc))
        except Exception as e:
            QMessageBox.critical(self, "重命名失败", str(e)); return
        
        # 更新 _songs 列表中的字典
        for s in self._songs:
            if s["path"] == old_str:
                s["path"] = new_str; s["name"] = new_name
                if Path(new_lrc).exists(): s["lrc_path"] = str(new_lrc)
                break
        
        self._build_filter_items(); self._do_refresh()
        # 重新选中
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            d = it.data(Qt.ItemDataRole.UserRole) if it else None
            if d and d.get("path") == new_str:
                self.table.selectRow(r); self.song_selected.emit(d); break

    def get_selected_songs(self):
        s = []
        for i in self.table.selectedItems():
            d = i.data(Qt.ItemDataRole.UserRole)
            if d and d not in s: s.append(d)
        return s

    def get_all_songs(self): return self._songs.copy()

    def update_song_status(self, fp, ok):
        for s in self._songs:
            if s["path"] == fp:
                s["has_lrc"] = ok
                if ok: s["lrc_path"] = str(Path(fp).with_suffix(".lrc"))
                break
        self._do_refresh()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole).get("path") == fp:
                self.table.selectRow(row)
                self.song_selected.emit(item.data(Qt.ItemDataRole.UserRole))
                break
