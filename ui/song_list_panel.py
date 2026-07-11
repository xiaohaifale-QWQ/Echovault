"""
歌曲列表面板 — 中间歌曲列表 + 状态标记
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QLineEdit, QHBoxLayout, QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush


# 歌词状态颜色
COLOR_HAS_LRC = QColor(76, 175, 80)    # 绿色：有歌词
COLOR_NO_LRC = QColor(158, 158, 158)   # 灰色：无歌词
COLOR_PROCESSING = QColor(255, 152, 0) # 橙色：识别中
COLOR_FAILED = QColor(244, 67, 54)     # 红色：失败


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


class SongListPanel(QWidget):
    """歌曲列表"""
    
    song_selected = pyqtSignal(dict)     # 选中歌曲信息
    model_updated = pyqtSignal()         # 列表更新
    
    COL_NAME = 0
    COL_STATUS = 1
    COL_SIZE = 2
    COL_FOLDER = 3
    COL_PATH = 4  # 隐藏列
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._songs: list[dict] = []  # 歌曲数据
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # 标题 + 搜索
        header = QHBoxLayout()
        title = QLabel("歌曲列表")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        header.addWidget(title)
        header.addStretch()
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索歌曲...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMaximumWidth(200)
        self.search_box.textChanged.connect(self._on_search)
        header.addWidget(self.search_box)
        
        layout.addLayout(header)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["歌曲名称", "状态", "大小", "文件夹", "路径"])
        self.table.setColumnHidden(self.COL_PATH, True)
        
        # 表头
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(self.COL_SIZE, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(self.COL_FOLDER, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_STATUS, 60)
        self.table.setColumnWidth(self.COL_SIZE, 70)
        self.table.setColumnWidth(self.COL_FOLDER, 100)
        
        # 选择行为
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        
        layout.addWidget(self.table)
    
    def load_songs(self, songs: list[dict]):
        """加载歌曲列表"""
        self._songs = songs
        self._refresh_table()
    
    def _refresh_table(self, filter_text: str = ""):
        """刷新表格显示"""
        self.table.setRowCount(0)
        
        filtered = self._songs
        if filter_text:
            text_lower = filter_text.lower()
            filtered = [s for s in self._songs if text_lower in s["name"].lower()]
        
        self.table.setRowCount(len(filtered))
        
        for row, song in enumerate(filtered):
            # 名称
            name_item = QTableWidgetItem(song["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, song)
            self.table.setItem(row, self.COL_NAME, name_item)
            
            # 状态
            status = "OK" if song.get("has_lrc") else "--"
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if song.get("has_lrc"):
                status_item.setForeground(QBrush(COLOR_HAS_LRC))
            self.table.setItem(row, self.COL_STATUS, status_item)
            
            # 大小
            size_item = QTableWidgetItem(_format_size(song.get("size", 0)))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, self.COL_SIZE, size_item)
            
            # 文件夹
            folder_item = QTableWidgetItem(song.get("folder", ""))
            self.table.setItem(row, self.COL_FOLDER, folder_item)
            
            # 路径（隐藏）
            path_item = QTableWidgetItem(song.get("path", ""))
            self.table.setItem(row, self.COL_PATH, path_item)
        
        self.model_updated.emit()
    
    def _on_search(self, text: str):
        """搜索过滤"""
        self._refresh_table(text)
    
    def _on_selection_changed(self):
        """选中行变化"""
        selected = self.get_selected_songs()
        if selected:
            self.song_selected.emit(selected[0])
    
    def get_selected_songs(self) -> list[dict]:
        """获取选中的歌曲"""
        songs = []
        for item in self.table.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data not in songs:
                songs.append(data)
        return songs
    
    def get_all_songs(self) -> list[dict]:
        """获取全部歌曲"""
        return self._songs.copy()
    
    def update_song_status(self, file_path: str, has_lrc: bool):
        """更新单首歌的状态（识别完成后回调）"""
        for song in self._songs:
            if song["path"] == file_path:
                song["has_lrc"] = has_lrc
                if has_lrc:
                    song["lrc_path"] = str(Path(file_path).with_suffix(".lrc"))
                break
        
        # 刷新当前显示
        self._refresh_table(self.search_box.text())
        
        # 重新触发选中
        selected = self.get_selected_songs()
        if selected:
            self.song_selected.emit(selected[0])
