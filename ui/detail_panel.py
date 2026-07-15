"""Song detail + lyrics preview panel"""
import os
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit,
    QGroupBox, QHBoxLayout, QFrame, QComboBox)
from PyQt6.QtCore import pyqtSignal
from core.lrc_parser import parse_lrc_file

class DetailPanel(QWidget):
    transcribe_clicked = pyqtSignal(str)
    edit_lyrics_clicked = pyqtSignal(str)
    translate_requested = pyqtSignal(str, str, str, str)
    batch_translate_requested = pyqtSignal(str, str, str)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._current_song = {}
        self._current_lrc_path = None
        self._showing_translation = False
        self._setup_ui()

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(6,6,6,6)
        t = QLabel("歌曲详情"); t.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        l.addWidget(t)
        
        ig = QGroupBox("歌曲信息"); il = QVBoxLayout(ig)
        self.lbl_name = QLabel("未选择歌曲"); self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet("font-size:14px;font-weight:bold"); il.addWidget(self.lbl_name)
        self.lbl_path = QLabel(""); self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color:#666;font-size:11px"); il.addWidget(self.lbl_path)
        self.lbl_status = QLabel(""); self.lbl_status.setStyleSheet("font-size:12px;margin-top:4px")
        il.addWidget(self.lbl_status); l.addWidget(ig)
        
        bl = QHBoxLayout()
        self.btn_transcribe = QPushButton("识别歌词"); self.btn_transcribe.setMinimumHeight(36)
        self.btn_transcribe.setStyleSheet("QPushButton{background:#1976D2;color:white;border-radius:4px;font-size:13px;font-weight:bold}QPushButton:hover{background:#1565C0}QPushButton:disabled{background:#ccc}")
        self.btn_transcribe.clicked.connect(lambda: self._current_song and self.transcribe_clicked.emit(self._current_song["path"]))
        bl.addWidget(self.btn_transcribe)
        self.btn_edit = QPushButton("编辑歌词"); self.btn_edit.setMinimumHeight(36); self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(lambda: self._current_song and self.edit_lyrics_clicked.emit(self._current_song["path"]))
        bl.addWidget(self.btn_edit); l.addLayout(bl)
        
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setStyleSheet("color:#ddd"); l.addWidget(line)
        
        lg = QGroupBox("歌词预览与翻译"); ll = QVBoxLayout(lg)
        translation_row = QHBoxLayout()
        self.translation_engine = QComboBox()
        self.translation_engine.addItem("AI 翻译", "ai")
        self.translation_engine.addItem("本地库", "local")
        translation_row.addWidget(self.translation_engine)
        self.translation_source = QComboBox()
        self.translation_target = QComboBox()
        for label, code in [("中", "zh"), ("英", "en"), ("日", "ja"), ("韩", "ko")]:
            self.translation_source.addItem(label, code)
            self.translation_target.addItem(label, code)
        translation_row.addWidget(self.translation_source)
        translation_row.addWidget(QLabel("→"))
        translation_row.addWidget(self.translation_target)
        self.btn_translate = QPushButton("翻译当前")
        self.btn_translate.setEnabled(False)
        self.btn_translate.clicked.connect(self._request_translation)
        translation_row.addWidget(self.btn_translate)
        self.btn_batch_translate = QPushButton("批量翻译")
        self.btn_batch_translate.clicked.connect(self._request_batch_translation)
        translation_row.addWidget(self.btn_batch_translate)
        self.btn_view_translation = QPushButton("查看译文")
        self.btn_view_translation.setEnabled(False)
        self.btn_view_translation.clicked.connect(self._toggle_translation_view)
        translation_row.addWidget(self.btn_view_translation)
        ll.addLayout(translation_row)
        self.lyrics_text = QTextEdit(); self.lyrics_text.setReadOnly(True)
        self.lyrics_text.setPlaceholderText("选择歌曲后可预览歌词...")
        self.lyrics_text.setStyleSheet("QTextEdit{font-family:Consolas,Microsoft YaHei;font-size:13px;background:#fafafa;border:none}")
        ll.addWidget(self.lyrics_text); l.addWidget(lg)
        self.reload_translation_settings()
        self.translation_target.currentIndexChanged.connect(
            lambda _index: self._refresh_translation_view_state()
        )

    @staticmethod
    def _select_data(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def reload_translation_settings(self):
        if self.config is None:
            return
        self._select_data(self.translation_engine, self.config.translation_engine)
        self._select_data(
            self.translation_source, self.config.translation_source_language
        )
        self._select_data(
            self.translation_target, self.config.translation_target_language
        )

    def show_song(self, song):
        if not song: return
        self._current_song = song
        self._current_lrc_path = None
        self._showing_translation = False
        self.lbl_name.setText(Path(song.get("name","?")).stem)
        self.lbl_path.setText(song.get("path",""))
        if song.get("material_type") == "video":
            captured_at = song.get("captured_at")
            timestamp = captured_at.strftime("%Y-%m-%d %H:%M:%S") if captured_at else "未知"
            self.lbl_status.setText(f"拍摄时间：{timestamp}（{song.get('timestamp_source', '未知来源')}）")
            self.lbl_status.setStyleSheet("color:#1976D2;font-size:12px")
            self.btn_transcribe.setVisible(True)
            self.btn_transcribe.setEnabled(True)
            self.btn_transcribe.setText("重新识别视频音频" if song.get("has_lrc") else "识别视频音频")
            self.btn_edit.setVisible(True)
            self.btn_edit.setEnabled(song.get("has_lrc", False))
            if song.get("has_lrc") and song.get("lrc_path"):
                self._current_lrc_path = Path(song["lrc_path"])
                self._load(song["lrc_path"])
            else:
                self.lyrics_text.setPlainText("将从视频中提取音轨并识别为同名 LRC。")
            self._refresh_translation_view_state()
            return
        self.btn_transcribe.setVisible(True)
        self.btn_edit.setVisible(True)
        has = song.get("has_lrc",False)
        self.lbl_status.setText("已有歌词" if has else "暂无歌词")
        self.lbl_status.setStyleSheet(f"color:{'#4CAF50' if has else '#999'};font-size:12px")
        # 已有歌词时仍应允许用户覆盖旧结果重新识别；此前这里把按钮
        # 标为“重新识别”后又同时禁用，导致该操作无法执行。
        self.btn_transcribe.setEnabled(True)
        self.btn_transcribe.setText("重新识别" if has else "识别歌词")
        self.btn_edit.setEnabled(has)
        if has and song.get("lrc_path"):
            self._current_lrc_path = Path(song["lrc_path"])
            self._load(song["lrc_path"])
        else: self.lyrics_text.clear()
        self._refresh_translation_view_state()

    def _request_translation(self):
        if not self._current_lrc_path:
            return
        self.translate_requested.emit(
            str(self._current_lrc_path),
            self.translation_engine.currentData(),
            self.translation_source.currentData(),
            self.translation_target.currentData(),
        )

    def _request_batch_translation(self):
        self.batch_translate_requested.emit(
            self.translation_engine.currentData(),
            self.translation_source.currentData(),
            self.translation_target.currentData(),
        )

    def _translated_path(self):
        if not self._current_lrc_path:
            return None
        from core.lyrics_translation import translation_output_path

        return translation_output_path(
            self._current_lrc_path, self.translation_target.currentData()
        )

    def _refresh_translation_view_state(self):
        translated_path = self._translated_path()
        available = bool(translated_path and translated_path.is_file())
        self.btn_translate.setEnabled(bool(self._current_lrc_path))
        self.btn_view_translation.setEnabled(available)
        if available and self._showing_translation:
            self._load(translated_path)
        if not available and self._showing_translation:
            self._showing_translation = False
            if self._current_lrc_path:
                self._load(self._current_lrc_path)
        self.btn_view_translation.setText("查看原文" if self._showing_translation else "查看译文")

    def _toggle_translation_view(self):
        translated_path = self._translated_path()
        if not self._current_lrc_path or not translated_path or not translated_path.is_file():
            return
        self._showing_translation = not self._showing_translation
        self._load(translated_path if self._showing_translation else self._current_lrc_path)
        self._refresh_translation_view_state()

    def translation_completed(self, source_path: str, translated_path: str):
        if self._current_lrc_path != Path(source_path):
            return
        self._showing_translation = True
        self._load(translated_path)
        self._refresh_translation_view_state()

    def _load(self, path):
        try:
            lrc = parse_lrc_file(path)
            lines = []; 
            for ln in sorted(lrc.lines, key=lambda x: x.timestamp):
                m,s=divmod(ln.timestamp,60); lines.append(f"[{int(m):02d}:{s:05.2f}] {ln.text}")
            self.lyrics_text.setPlainText("\n".join(lines))
        except Exception as e: self.lyrics_text.setPlainText(f"load error: {e}")
