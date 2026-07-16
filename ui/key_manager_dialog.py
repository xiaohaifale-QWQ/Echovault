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
            "保存后请到“模型库 → 在线识别模型”选择 Groq 或讯飞。"
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color:#5B6573;padding:4px 0")
        layout.addWidget(notice)

        form = QFormLayout()
        self.groq_input = self._key_input(config.groq_api_key)
        self.groq_proxy_input = QLineEdit(config.groq_proxy_url)
        self.groq_proxy_input.setPlaceholderText("可选，例如 http://127.0.0.1:7890")
        self.xunfei_app_id_input = QLineEdit(config.xunfei_app_id)
        self.xunfei_app_id_input.setPlaceholderText("讯飞开放平台应用 AppID")
        self.xunfei_api_key_input = self._key_input(config.xunfei_api_key)
        self.xunfei_api_secret_input = self._key_input(config.xunfei_api_secret)
        self.ai_input = self._key_input(config.ai_model_api_key)
        form.addRow(
            self._provider_label("Groq API Key:", "https://console.groq.com/keys"),
            self.groq_input,
        )
        form.addRow("Groq 代理地址（可选）:", self.groq_proxy_input)
        form.addRow(
            self._provider_label("讯飞 AppID:", "https://console.xfyun.cn/"),
            self.xunfei_app_id_input,
        )
        form.addRow("讯飞 API Key:", self.xunfei_api_key_input)
        form.addRow("讯飞 API Secret:", self.xunfei_api_secret_input)
        xunfei_hint = QLabel("讯飞语音听写需要三项全部填写；请在同一个讯飞应用的服务页获取。")
        xunfei_hint.setStyleSheet("font-size:11px;color:#7A838D")
        xunfei_hint.setWordWrap(True)
        form.addRow("", xunfei_hint)
        form.addRow(
            self._provider_label("DeepSeek API Key:", "https://platform.deepseek.com/api_keys"),
            self.ai_input,
        )
        self.ai_base_url = QLineEdit(config.ai_base_url)
        self.ai_model_name = QLineEdit(config.ai_model_name)
        form.addRow("AI 接口地址:", self.ai_base_url)
        form.addRow("AI 模型名称:", self.ai_model_name)
        layout.addLayout(form)

        future = QLabel("AI Key 仅在用户主动发送 AI 对话时使用；不会上传本地素材文件。")
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

    @staticmethod
    def _provider_label(text: str, url: str) -> QLabel:
        label = QLabel(f'<a href="{url}">{text}</a>')
        label.setOpenExternalLinks(True)
        label.setToolTip("打开服务官网")
        return label

    def _save(self) -> None:
        self.config.groq_api_key = self.groq_input.text().strip()
        self.config.groq_proxy_url = self.groq_proxy_input.text().strip()
        self.config.xunfei_app_id = self.xunfei_app_id_input.text().strip()
        self.config.xunfei_api_key = self.xunfei_api_key_input.text().strip()
        self.config.xunfei_api_secret = self.xunfei_api_secret_input.text().strip()
        self.config.ai_model_api_key = self.ai_input.text().strip()
        self.config.ai_base_url = self.ai_base_url.text().strip().rstrip("/") or "https://api.deepseek.com"
        self.config.ai_model_name = self.ai_model_name.text().strip() or "deepseek-chat"
        for name, value in (
            ("GROQ_API_KEY", self.config.groq_api_key),
            ("XUNFEI_APP_ID", self.config.xunfei_app_id),
            ("XUNFEI_API_KEY", self.config.xunfei_api_key),
            ("XUNFEI_API_SECRET", self.config.xunfei_api_secret),
            ("ECHOVAULT_AI_API_KEY", self.config.ai_model_api_key),
        ):
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
        try:
            config_manager.config = self.config
            config_manager.save()
        except OSError as exc:
            QMessageBox.critical(self, "密钥管理", f"无法保存本机配置：{exc}")
            return
        self.accept()
