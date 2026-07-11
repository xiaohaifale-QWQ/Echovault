"""
详情面板 — 右侧歌曲详情、歌词预览、操作按钮
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit,
    QGroupBox, QHBoxLayout, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.lrc_parser import parse_lrc_file


class DetailPanel(QWidget):
    """右侧详情面板"""
    
    transcribe_clicked = pyqtSignal(str)     # 请求识别，参数文件路径
    edit_lyrics_clicked = pyqtSignal(str)    # 请求编辑歌词
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_song: dict = {}
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        
        # 标题
        title = QLabel("歌曲详情")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        layout.addWidget(title)
        
        # 歌曲信息
        self.info_group = QGroupBox("歌曲信息")
        info_layout = QVBoxLayout(self.info_group)
        
        self.lbl_name = QLabel("未选择歌曲")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet("font-size: 14px; font-weight: bold;")
        info_layout.addWidget(self.lbl_name)
        
        self.lbl_path = QLabel("")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.lbl_path)
        
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 12px; margin-top: 4px;")
        info_layout.addWidget(self.lbl_status)
        
        layout.addWidget(self.info_group)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.btn_transcribe = QPushButton("识别歌词")
        self.btn_transcribe.setMinimumHeight(36)
        self.btn_transcribe.setStyleSheet("""
            QPushButton {
                background-color: #1976D2; color: white;
                border-radius: 4px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1565C0; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.btn_transcribe.clicked.connect(self._on_transcribe)
        btn_layout.addWidget(self.btn_transcribe)
        
        self.btn_edit = QPushButton("编辑歌词")
        self.btn_edit.setMinimumHeight(36)
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.btn_edit)
        
        layout.addLayout(btn_layout)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)
        
        # 歌词预览
        self.lyrics_group = QGroupBox("歌词预览")
        lyrics_layout = QVBoxLayout(self.lyrics_group)
        
        self.lyrics_text = QTextEdit()
        self.lyrics_text.setReadOnly(True)
        self.lyrics_text.setPlaceholderText("选择歌曲后可预览歌词...")
        self.lyrics_text.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Microsoft YaHei', monospace;
                font-size: 13px;
                background-color: #fafafa;
                border: none;
            }
        """)
        lyrics_layout.addWidget(self.lyrics_text)
        
        layout.addWidget(self.lyrics_group)
    
    def show_song(self, song: dict):
        """显示歌曲详情"""
        if not song:
            return
        
        self._current_song = song
        
        # 基本信息
        self.lbl_name.setText(song.get("name", "未知"))
        self.lbl_path.setText(song.get("path", ""))
        
        # 状态
        has_lrc = song.get("has_lrc", False)
        if has_lrc:
            self.lbl_status.setText("已有歌词")
            self.lbl_status.setStyleSheet("color: #4CAF50; font-size: 12px; margin-top: 4px;")
        else:
            self.lbl_status.setText("⏳ 暂无歌词")
            self.lbl_status.setStyleSheet("color: #999; font-size: 12px; margin-top: 4px;")
        
        # 按钮状态
        self.btn_transcribe.setEnabled(not has_lrc)
        self.btn_transcribe.setText("重新识别" if has_lrc else "识别歌词")
        self.btn_edit.setEnabled(has_lrc)
        
        # 歌词预览
        if has_lrc and song.get("lrc_path"):
            self._load_lyrics(song["lrc_path"])
        else:
            self.lyrics_text.clear()
    
    def _load_lyrics(self, lrc_path: str):
        """加载并显示 LRC 歌词"""
        try:
            lrc = parse_lrc_file(lrc_path)
            lines = []
            for line in sorted(lrc.lines, key=lambda l: l.timestamp):
                minutes = int(line.timestamp // 60)
                seconds = line.timestamp % 60
                ts = f"[{minutes:02d}:{seconds:05.2f}]"
                lines.append(f"{ts} {line.text}")
            
            self.lyrics_text.setPlainText("\n".join(lines))
        except Exception as e:
            self.lyrics_text.setPlainText(f"加载歌词失败: {e}")
    
    def _on_transcribe(self):
        """点击识别按钮"""
        if self._current_song:
            self.transcribe_clicked.emit(self._current_song["path"])
    
    def _on_edit(self):
        """点击编辑按钮"""
        if self._current_song:
            self.edit_lyrics_clicked.emit(self._current_song["path"])
