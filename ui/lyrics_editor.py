"""
歌词编辑器对话框
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QMessageBox,
    QDoubleSpinBox, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.lrc_parser import parse_lrc_file, LRCFile, LyricLine, format_timestamp


class LyricsEditorDialog(QDialog):
    """LRC 歌词编辑器"""
    
    def __init__(self, audio_path: str, lrc_path: str, parent=None):
        super().__init__(parent)
        
        self.audio_path = Path(audio_path)
        self.lrc_path = lrc_path
        
        self._lrc: LRCFile = None
        self._modified = False
        
        self._setup_ui()
        
        # 加载歌词
        if os.path.exists(lrc_path):
            self._load_lrc()
        else:
            self._create_empty()
    
    def _setup_ui(self):
        self.setWindowTitle(f"编辑歌词 — {self.audio_path.name}")
        self.setMinimumSize(700, 550)
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # 提示
        hint = QLabel(
            "提示: 双击单元格编辑文本 | 右键删除行 | 底部按钮添加新行 | 全局偏移调整时间"
        )
        hint.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        layout.addWidget(hint)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["时间戳", "开始(s)", "歌词文本"])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 80)
        
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.table)
        
        # 底部按钮
        bottom = QHBoxLayout()
        
        self.btn_add = QPushButton("+ 添加行")
        self.btn_add.clicked.connect(self._add_line)
        bottom.addWidget(self.btn_add)
        
        self.btn_delete = QPushButton("删除选中行")
        self.btn_delete.clicked.connect(self._delete_selected)
        bottom.addWidget(self.btn_delete)
        
        bottom.addStretch()
        
        # 全局偏移
        bottom.addWidget(QLabel("全局偏移:"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-30.0, 30.0)
        self.offset_spin.setValue(0.0)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setSuffix(" 秒")
        self.offset_spin.valueChanged.connect(self._on_offset_changed)
        bottom.addWidget(self.offset_spin)
        
        layout.addLayout(bottom)
        
        # 确定/取消
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _load_lrc(self):
        """加载 LRC 文件"""
        try:
            self._lrc = parse_lrc_file(self.lrc_path)
            self._populate_table()
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法解析 LRC 文件: {e}")
            self._create_empty()
    
    def _create_empty(self):
        """创建空白 LRC"""
        self._lrc = LRCFile()
        self._lrc.by = "MusicSync"
        self._lrc.title = self.audio_path.stem
        self._populate_table()
    
    def _populate_table(self):
        """填充表格"""
        self.table.setRowCount(0)
        self._original_offsets = []  # 记录原始偏移，用于全局偏移计算
        
        for i, line in enumerate(sorted(self._lrc.lines, key=lambda l: l.timestamp)):
            self.table.insertRow(i)
            
            # 时间戳显示
            ts_item = QTableWidgetItem(format_timestamp(line.timestamp))
            ts_item.setFlags(ts_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, ts_item)
            
            # 秒数
            sec_item = QTableWidgetItem(f"{line.timestamp:.2f}")
            sec_item.setFlags(sec_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, sec_item)
            
            # 歌词文本
            text_item = QTableWidgetItem(line.text)
            self.table.setItem(i, 2, text_item)
            
            self._original_offsets.append(0.0)
    
    def _sync_table_to_lrc(self):
        """将表格数据同步回 LRC 对象"""
        lines = []
        for row in range(self.table.rowCount()):
            ts_text = self.table.item(row, 0)
            text_item = self.table.item(row, 2)
            
            if ts_text and text_item:
                ts = self._parse_timestamp(ts_text.text())
                text = text_item.text().strip()
                if text:
                    lines.append(LyricLine(ts, text))
        
        self._lrc.lines = lines
    
    def _parse_timestamp(self, ts_str: str) -> float:
        """解析时间戳字符串"""
        import re
        m = re.match(r"\[(\d+):(\d+\.?\d*)\]", ts_str)
        if m:
            return int(m.group(1)) * 60 + float(m.group(2))
        return 0.0
    
    def _add_line(self):
        """添加新行"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # 默认时间戳在最后一行之后
        last_ts = 0.0
        if row > 0:
            last_item = self.table.item(row - 1, 1)
            if last_item:
                last_ts = float(last_item.text()) + 3.0  # 默认间隔3秒
        
        ts_item = QTableWidgetItem(format_timestamp(last_ts))
        ts_item.setFlags(ts_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, ts_item)
        
        sec_item = QTableWidgetItem(f"{last_ts:.2f}")
        sec_item.setFlags(sec_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, sec_item)
        
        text_item = QTableWidgetItem("")
        self.table.setItem(row, 2, text_item)
        
        self.table.editItem(text_item)
        self._original_offsets.append(self.offset_spin.value())
        self._modified = True
    
    def _delete_selected(self):
        """删除选中行"""
        selected = self.table.selectedItems()
        if not selected:
            return
        
        rows = sorted(set(item.row() for item in selected), reverse=True)
        for row in rows:
            self.table.removeRow(row)
            if row < len(self._original_offsets):
                self._original_offsets.pop(row)
        
        self._modified = True
    
    def _on_offset_changed(self, delta: float):
        """全局偏移改变"""
        # 重新填充表格（基于原始偏移）
        if not self._lrc:
            return
        
        for row in range(self.table.rowCount()):
            if row < len(self._original_offsets):
                original_delta = self._original_offsets[row]
                effective_delta = delta - original_delta
                
                line = self._lrc.lines[row] if row < len(self._lrc.lines) else None
                if line:
                    new_ts = line.timestamp + effective_delta
                    if new_ts < 0:
                        new_ts = 0
                    
                    ts_item = self.table.item(row, 0)
                    if ts_item:
                        ts_item.setText(format_timestamp(new_ts))
                    
                    sec_item = self.table.item(row, 1)
                    if sec_item:
                        sec_item.setText(f"{new_ts:.2f}")
        
        self._modified = True
    
    def _on_save(self):
        """保存"""
        # 同步并应用偏移
        self._sync_table_to_lrc()
        if self.offset_spin.value() != 0:
            self._lrc.apply_offset(self.offset_spin.value())
        
        # 写入文件
        content = self._lrc.to_string()
        with open(self.lrc_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        self._modified = False
        self.accept()
    
    def closeEvent(self, event):
        """关闭前确认"""
        if self._modified:
            reply = QMessageBox.question(
                self, "未保存", "有未保存的修改，是否保存？",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._on_save()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
