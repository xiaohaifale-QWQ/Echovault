"""Local-only API key management dialog."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from core.config import AppConfig, config_manager


class KeyManagerDialog(QDialog):
    """Edit locally stored provider credentials without placing them in preferences."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("密钥管理")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        notice = QLabel(
            "密钥只保存到本机配置文件，不会上传到 Echovault 服务器。"
            "选择在线识别时，Groq 密钥才会被用于连接 Groq 服务。"
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color:#5B6573;padding:4px 0")
        layout.addWidget(notice)

        form = QFormLayout()
        self.groq_input = self._key_input(config.groq_api_key)
        self.xunfei_input = self._key_input(config.xunfei_api_key)
        self.ai_input = self._key_input(config.ai_model_api_key)
        form.addRow("Groq API Key:", self.groq_input)
        form.addRow("讯飞 API Key:", self.xunfei_input)
        form.addRow("DeepSeek API Key:", self.ai_input)
        self.ai_base_url = QLineEdit(config.ai_base_url)
        self.ai_model_name = QLineEdit(config.ai_model_name)
        form.addRow("AI 接口地址:", self.ai_base_url)
        form.addRow("AI 模型名称:", self.ai_model_name)
        layout.addLayout(form)

        future = QLabel("AI 模式尚未启用；此处只预先保存密钥，不会发起任何 AI 请求。")
        future.setStyleSheet("font-size:11px;color:#7A838D")
        future.setWordWrap(True)
        layout.addWidget(future)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _key_input(value: str) -> QLineEdit:
        field = QLineEdit(value)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText("留空以删除本机保存的密钥")
        return field

    def _save(self) -> None:
        self.config.groq_api_key = self.groq_input.text().strip()
        self.config.xunfei_api_key = self.xunfei_input.text().strip()
        self.config.ai_model_api_key = self.ai_input.text().strip()
        self.config.ai_base_url = self.ai_base_url.text().strip().rstrip("/") or "https://api.deepseek.com"
        self.config.ai_model_name = self.ai_model_name.text().strip() or "deepseek-chat"
        for name, value in (
            ("GROQ_API_KEY", self.config.groq_api_key),
            ("XUNFEI_API_KEY", self.config.xunfei_api_key),
            ("ECHOVAULT_AI_API_KEY", self.config.ai_model_api_key),
        ):
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
        config_manager.config = self.config
        try:
            config_manager.save()
        except OSError as exc:
            QMessageBox.critical(self, "密钥管理", f"无法保存本机配置：{exc}")
            return
        self.accept()
