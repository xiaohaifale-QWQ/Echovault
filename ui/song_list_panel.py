"""Song list with filters + rename + instrumental marking"""
import os, json
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QLineEdit, QHBoxLayout, QAbstractItemView, QComboBox, QMessageBox, QPushButton, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QAction

COLOR_HAS_LRC = QColor(76, 175, 80)
COLOR_INST = QColor(255, 152, 0)

def _fmt_size(b): return f"{b/1024:.0f}KB" if b>1024 else f"{b}B"

class SongListPanel(QWidget):
    song_selected = pyqtSignal(dict)
    model_updated = pyqtSignal()
    batch_transcribe = pyqtSignal()
    COL_NAME, COL_FORMAT, COL_STATUS, COL_SIZE, COL_FOLDER, COL_PATH = 0, 1, 2, 3, 4, 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs = []; self._instrumental = set(); self._auto_inst = set(); self._inst_file = None
        self._setup_ui()
        self.lyric_filter.setCurrentIndex(2)  # default "no lyrics"
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(4,4,4,4)
        h = QHBoxLayout()
        t = QLabel("歌曲列表"); t.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        h.addWidget(t); h.addStretch()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("搜索...")
        self.search_box.setClearButtonEnabled(True); self.search_box.setMaximumWidth(120)
        self.search_box.textChanged.connect(self._do_refresh); h.addWidget(self.search_box)
        self.lyric_filter = QComboBox(); self.lyric_filter.addItems(["全部","有歌词","无歌词","纯音乐"])
        self.lyric_filter.setMaximumWidth(70); self.lyric_filter.currentIndexChanged.connect(self._do_refresh)
        h.addWidget(self.lyric_filter)
        self.fmt_filter = QComboBox(); self.fmt_filter.addItem("全部格式")
        self.fmt_filter.setMaximumWidth(85); self.fmt_filter.currentIndexChanged.connect(self._do_refresh)
        h.addWidget(self.fmt_filter)
        self.btn_batch = QPushButton("批量识别"); self.btn_batch.setStyleSheet(
            "QPushButton{background:#1976D2;color:white;border-radius:3px;padding:2px 8px;font-size:12px}"
            "QPushButton:hover{background:#1565C0}")
        self.btn_batch.clicked.connect(self.batch_transcribe.emit); h.addWidget(self.btn_batch)
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
        self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False); self.table.itemSelectionChanged.connect(self._on_sel)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        l.addWidget(self.table)

    def _load_instrumental(self, root_dir):
        """Load instrumental markers from JSON file in root directory"""
        self._inst_file = Path(root_dir) / ".musicsync_instrumental.json"
        self._instrumental = set()
        if self._inst_file.exists():
            try:
                data = json.loads(self._inst_file.read_text(encoding="utf-8"))
                self._instrumental = set(data.get("instrumental", []))
            except: pass

    def _save_instrumental(self):
        if self._inst_file:
            data = {"instrumental": sorted(self._instrumental)}
            self._inst_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_fmt_items(self):
        formats = sorted(set(Path(s["name"]).suffix.upper().lstrip(".") for s in self._songs))
        self.fmt_filter.blockSignals(True); cur = self.fmt_filter.currentText()
        self.fmt_filter.clear(); self.fmt_filter.addItem("全部格式")
        for f in formats: self.fmt_filter.addItem(f)
        idx = self.fmt_filter.findText(cur); self.fmt_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.fmt_filter.blockSignals(False)

    def load_songs(self, songs, root_dir=""):
        self._songs = songs
        if root_dir: self._load_instrumental(root_dir)
        for s in self._songs:
            s["instrumental"] = s["path"] in self._instrumental
        self._build_fmt_items(); self._do_refresh()

    def _do_refresh(self, *a):
        self.table.setRowCount(0); f = self._songs
        t = self.search_box.text().lower()
        if t: f = [s for s in f if t in Path(s["name"]).stem.lower()]
        lf = self.lyric_filter.currentIndex()
        if lf == 1: f = [s for s in f if s.get("has_lrc") and not s.get("instrumental")]
        elif lf == 2: f = [s for s in f if not s.get("has_lrc") and not s.get("instrumental")]
        elif lf == 3: f = [s for s in f if s.get("instrumental")]
        ff = self.fmt_filter.currentText()
        if ff and ff != "全部格式":
            f = [s for s in f if Path(s["name"]).suffix.upper().lstrip(".") == ff.upper()]
        self.table.setRowCount(len(f))
        for i, s in enumerate(f):
            n = QTableWidgetItem(Path(s["name"]).stem); n.setData(Qt.ItemDataRole.UserRole, s); self.table.setItem(i, 0, n)
            fmt = Path(s["name"]).suffix.lstrip(".").upper()
            fi = QTableWidgetItem(fmt); fi.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.table.setItem(i, 1, fi)
            if s.get("instrumental_auto"): st = "纯?"; c = COLOR_INST
            elif s.get("instrumental"): st = "纯"; c = COLOR_INST
            elif s.get("has_lrc"): st = "OK"; c = COLOR_HAS_LRC
            else: st = "--"; c = QColor(158,158,158)
            si = QTableWidgetItem(st); si.setTextAlignment(Qt.AlignmentFlag.AlignCenter); si.setForeground(QBrush(c))
            self.table.setItem(i, 2, si)
            zi = QTableWidgetItem(_fmt_size(s.get("size",0)))
            zi.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); self.table.setItem(i, 3, zi)
            self.table.setItem(i, 4, QTableWidgetItem(s.get("folder","")))
            self.table.setItem(i, 5, QTableWidgetItem(s.get("path","")))
        self.model_updated.emit()

    def _on_sel(self):
        sel = self.get_selected_songs()
        if sel: self.song_selected.emit(sel[0])

    def _on_context_menu(self, pos):
        """右键菜单：标记/取消纯音乐"""
        items = self.table.selectedItems()
        if not items: return
        songs = self.get_selected_songs()
        if not songs: return
        all_inst = all(s.get("instrumental") for s in songs)
        menu = QMenu(self)
        if all_inst:
            act = QAction("取消纯音乐标记", self)
            act.triggered.connect(lambda: self._toggle_instrumental(songs, False))
        else:
            act = QAction("标记为纯音乐", self)
            act.triggered.connect(lambda: self._toggle_instrumental(songs, True))
        menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def mark_instrumental(self, fp, auto=False):
        """标记为纯音乐（auto=True 表示自动检测）"""
        if auto:
            self._auto_inst.add(fp)
        self._instrumental.add(fp)
        for s in self._songs:
            if s["path"] == fp:
                s["instrumental"] = True
                s["instrumental_auto"] = auto
                break
        self._save_instrumental()
        self._do_refresh()

    def _toggle_instrumental(self, songs, mark):
        for s in songs:
            s["instrumental"] = mark
            s.pop("instrumental_auto", None)
            if mark: self._instrumental.add(s["path"]); self._auto_inst.discard(s["path"])
            else: self._instrumental.discard(s["path"]); self._auto_inst.discard(s["path"])
        self._save_instrumental()
        # 如果当前筛选会隐藏这些歌曲，自动切换到"全部"
        lf = self.lyric_filter.currentIndex()
        if mark and lf in (1, 2):  # "有歌词"或"无歌词"
            self.lyric_filter.setCurrentIndex(0)  # 切换到"全部"
        elif not mark and lf == 3:  # "纯音乐"
            self.lyric_filter.setCurrentIndex(0)
        self._do_refresh()

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
        new_name = new_stem + old_path.suffix; new_path = old_path.parent / new_name
        old_str = str(old_path); new_str = str(new_path)
        try:
            os.rename(old_str, new_str)
            old_lrc = old_path.with_suffix(".lrc"); new_lrc = new_path.with_suffix(".lrc")
            if old_lrc.exists(): os.rename(str(old_lrc), str(new_lrc))
        except Exception as e: QMessageBox.critical(self, "rename failed", str(e)); return
        for s in self._songs:
            if s["path"] == old_str: s["path"] = new_str; s["name"] = new_name
            if Path(new_lrc).exists(): s["lrc_path"] = str(new_lrc)
            break
        self._build_fmt_items(); self._do_refresh()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            d = it.data(Qt.ItemDataRole.UserRole) if it else None
            if d and d.get("path") == new_str: self.table.selectRow(r); self.song_selected.emit(d); break

    def get_selected_songs(self):
        s = []; 
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
                self.table.selectRow(row); self.song_selected.emit(item.data(Qt.ItemDataRole.UserRole))
                break
