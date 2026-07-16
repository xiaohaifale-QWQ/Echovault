"""Song detail + lyrics preview panel"""
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.lrc_parser import parse_lrc_file


class DetailPanel(QWidget):
    transcribe_clicked = pyqtSignal(str)
    edit_lyrics_clicked = pyqtSignal(str)
    translate_requested = pyqtSignal(str, str, str, str)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._current_song = {}
        self._current_lrc_path = None
        self._showing_translation = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(9)

        ig = QGroupBox("当前素材"); il = QVBoxLayout(ig)
        self.lbl_name = QLabel("未选择歌曲"); self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet("font-size:15px;font-weight:700"); il.addWidget(self.lbl_name)
        self.lbl_path = QLabel(""); self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color:#667085;font-size:11px"); il.addWidget(self.lbl_path)
        self.lbl_status = QLabel(""); self.lbl_status.setStyleSheet("font-size:12px;margin-top:4px")
        il.addWidget(self.lbl_status)
        layout.addWidget(ig)

        actions = QHBoxLayout()
        self.btn_transcribe = QPushButton("识别歌词")
        self.btn_transcribe.setMinimumHeight(36)
        self.btn_transcribe.clicked.connect(
            lambda: self._current_song
            and self.transcribe_clicked.emit(self._current_song["path"])
        )
        actions.addWidget(self.btn_transcribe)
        self.btn_edit = QPushButton("编辑歌词")
        self.btn_edit.setMinimumHeight(36)
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(
            lambda: self._current_song
            and self.edit_lyrics_clicked.emit(self._current_song["path"])
        )
        actions.addWidget(self.btn_edit)
        layout.addLayout(actions)

        lg = QGroupBox("翻译"); ll = QVBoxLayout(lg)
        translation_hint = QLabel("左侧保留原歌词；这里仅显示译文，避免同一歌词重复出现。")
        translation_hint.setWordWrap(True)
        translation_hint.setStyleSheet("color:#667085;font-size:11px")
        ll.addWidget(translation_hint)
        translation_form = QFormLayout()
        self.translation_engine = QComboBox()
        self.translation_engine.addItem("AI 翻译", "ai")
        self.translation_engine.addItem("本地库", "local")
        translation_form.addRow("翻译引擎", self.translation_engine)
        self.translation_source = QComboBox()
        self.translation_target = QComboBox()
        self.translation_source.addItem("自动检测", "auto")
        for label, code in [("中", "zh"), ("英", "en"), ("日", "ja"), ("韩", "ko")]:
            self.translation_source.addItem(label, code)
            self.translation_target.addItem(label, code)
        language_row = QHBoxLayout()
        language_row.addWidget(self.translation_source, 1)
        language_row.addWidget(QLabel("→"))
        language_row.addWidget(self.translation_target, 1)
        translation_form.addRow("语言", language_row)
        ll.addLayout(translation_form)
        translation_actions = QHBoxLayout()
        self.btn_translate = QPushButton("翻译当前")
        self.btn_translate.setEnabled(False)
        self.btn_translate.clicked.connect(self._request_translation)
        translation_actions.addWidget(self.btn_translate)
        self.btn_view_translation = QPushButton("查看已有译文")
        self.btn_view_translation.setEnabled(False)
        self.btn_view_translation.clicked.connect(self._toggle_translation_view)
        translation_actions.addWidget(self.btn_view_translation)
        ll.addLayout(translation_actions)
        self.lyrics_text = QTextEdit(); self.lyrics_text.setReadOnly(True)
        self.lyrics_text.setPlaceholderText("翻译完成后，译文会显示在这里。")
        self.lyrics_text.setMinimumHeight(170)
        self.lyrics_text.setStyleSheet(
            "QTextEdit{font-family:Consolas,Microsoft YaHei UI;font-size:13px;"
            "background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:8px}"
        )
        ll.addWidget(self.lyrics_text, 1)
        layout.addWidget(lg, 1)
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
            source = song.get("timestamp_source", "未知来源")
            self.lbl_status.setText(f"拍摄时间：{timestamp}（{source}）")
            self.lbl_status.setStyleSheet("color:#1976D2;font-size:12px")
            self.btn_transcribe.setVisible(True)
            self.btn_transcribe.setEnabled(True)
            self.btn_transcribe.setText(
                "重新识别视频音频" if song.get("has_lrc") else "识别视频音频"
            )
            self.btn_edit.setVisible(True)
            self.btn_edit.setEnabled(song.get("has_lrc", False))
            if song.get("has_lrc") and song.get("lrc_path"):
                self._current_lrc_path = Path(song["lrc_path"])
                self.lyrics_text.clear()
            else:
                self.lyrics_text.setPlainText("识别视频音频后可在这里生成译文。")
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
            self.lyrics_text.clear()
        else:
            self.lyrics_text.setPlainText("识别歌词后可在这里生成译文。")
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
            self.lyrics_text.clear()
        self.btn_view_translation.setText(
            "刷新已有译文" if self._showing_translation else "查看已有译文"
        )

    def _toggle_translation_view(self):
        translated_path = self._translated_path()
        if not self._current_lrc_path or not translated_path or not translated_path.is_file():
            return
        self._showing_translation = True
        self._load(translated_path)
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
            lines = []
            for ln in sorted(lrc.lines, key=lambda x: x.timestamp):
                m,s=divmod(ln.timestamp,60); lines.append(f"[{int(m):02d}:{s:05.2f}] {ln.text}")
            self.lyrics_text.setPlainText("\n".join(lines))
        except Exception as e: self.lyrics_text.setPlainText(f"load error: {e}")
