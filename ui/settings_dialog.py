"""
设置对话框
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QCheckBox, QPushButton,
    QGroupBox, QLabel, QDialogButtonBox, QFileDialog,
)
from PyQt6.QtCore import Qt

from core.config import AppConfig, ASRConfig, config_manager


class SettingsDialog(QDialog):
    """偏好设置"""
    
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()
        self._load_config()
    
    def _setup_ui(self):
        self.setWindowTitle("偏好设置")
        self.setMinimumWidth(480)
        
        layout = QVBoxLayout(self)
        
        # ── ASR 设置 ──
        asr_group = QGroupBox("语音识别 (ASR)")
        asr_form = QFormLayout(asr_group)
        
        # Provider 选择
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Groq Whisper (云端, 免费)", "groq")
        self.provider_combo.addItem("本地 Whisper (离线, 需GPU)", "local")
        self.provider_combo.addItem("阿里云 ASR (扩展)", "aliyun")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        asr_form.addRow("识别引擎:", self.provider_combo)
        
        # API Key
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("输入 API Key...")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        asr_form.addRow("Groq API Key:", self.api_key_input)
        
        api_hint = QLabel(
            '<a href="https://console.groq.com/keys" style="color: #1976D2;">'
            '免费获取 Groq API Key →</a>'
        )
        api_hint.setOpenExternalLinks(True)
        api_hint.setStyleSheet("font-size: 11px; margin-left: 4px;")
        asr_form.addRow("", api_hint)
        
        # 语言
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("自动检测", None)
        self.lang_combo.addItem("中文 (zh)", "zh")
        self.lang_combo.addItem("英语 (en)", "en")
        self.lang_combo.addItem("日语 (ja)", "ja")
        self.lang_combo.addItem("韩语 (ko)", "ko")
        asr_form.addRow("默认语言:", self.lang_combo)
        
        # 本地模型（仅本地模式显示）
        self.model_combo = QComboBox()
        self.model_combo.addItem("tiny (最快, 39M)", "tiny")
        self.model_combo.addItem("base (推荐, 74M)", "base")
        self.model_combo.addItem("small (较准, 244M)", "small")
        self.model_combo.addItem("medium (更准, 769M)", "medium")
        self.model_combo.setVisible(False)
        asr_form.addRow("本地模型:", self.model_combo)
        
        # 人声分离
        self.vocal_sep_check = QCheckBox("启用 Demucs 人声分离（每首歌额外 1-3 分钟，提升准确率）")
        asr_form.addRow("", self.vocal_sep_check)
        
        layout.addWidget(asr_group)
        
        # ── 歌词设置 ──
        lrc_group = QGroupBox("歌词输出")
        lrc_form = QFormLayout(lrc_group)
        
        # 输出目录
        dir_layout = QHBoxLayout()
        self.lrc_dir_input = QLineEdit()
        self.lrc_dir_input.setPlaceholderText("留空 = 与音频文件同目录")
        dir_layout.addWidget(self.lrc_dir_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_lrc_dir)
        dir_layout.addWidget(browse_btn)
        
        lrc_form.addRow("LRC 输出目录:", dir_layout)
        
        layout.addWidget(lrc_group)
        
        # ── 按钮 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _load_config(self):
        """从 config 加载值到 UI"""
        # Provider
        index = self.provider_combo.findData(self.config.asr.provider)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        
        # API Key
        self.api_key_input.setText(self.config.groq_api_key)
        
        # Language
        idx = self.lang_combo.findData(self.config.asr.language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        
        # Model
        idx = self.model_combo.findData(self.config.asr.local_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        
        # Vocal separation
        self.vocal_sep_check.setChecked(self.config.asr.use_vocal_separation)
        
        # LRC dir
        if self.config.output_lrc_dir:
            self.lrc_dir_input.setText(self.config.output_lrc_dir)
    
    def _on_provider_changed(self, idx: int):
        """Provider 切换时显示/隐藏相关选项"""
        provider = self.provider_combo.itemData(idx)
        is_local = (provider == "local")
        self.api_key_input.setVisible(not is_local)
        self.model_combo.setVisible(is_local)
    
    def _browse_lrc_dir(self):
        """选择 LRC 输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择歌词输出目录")
        if dir_path:
            self.lrc_dir_input.setText(dir_path)
    
    def _on_save(self):
        """保存设置"""
        # ASR
        self.config.asr.provider = self.provider_combo.currentData()
        self.config.asr.language = self.lang_combo.currentData()
        self.config.asr.local_model = self.model_combo.currentData()
        self.config.asr.use_vocal_separation = self.vocal_sep_check.isChecked()
        
        # API Key
        key = self.api_key_input.text().strip()
        self.config.groq_api_key = key
        if key:
            os.environ["GROQ_API_KEY"] = key
        
        # LRC
        lrc_dir = self.lrc_dir_input.text().strip()
        self.config.output_lrc_dir = lrc_dir if lrc_dir else None
        
        # 持久化
        config_manager.config = self.config
        config_manager.save()
        
        self.accept()
