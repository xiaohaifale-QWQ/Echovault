"""Dockable DeepSeek chat panel for the desktop application."""
# ruff: noqa: E501

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.ai_assistant import SYSTEM_PROMPT, AISettings, chat
from core.config import AppConfig


class AIChatWorker(QThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, settings: AISettings, question: str, history: list[dict[str, str]], parent=None):
        super().__init__(parent)
        self._settings = settings
        self._question = question
        self._history = history

    def run(self):
        try:
            self.completed.emit(chat(self._settings, self._question, self._history))
        except RuntimeError as exc:
            self.failed.emit(str(exc))


class AIChatPanel(QWidget):
    """Conversation UI that always sends the built-in manual as the system prompt."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._history: list[dict[str, str]] = []
        self._worker: AIChatWorker | None = None
        self.setMinimumWidth(310)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Echovault AI 助手")
        title.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        layout.addWidget(title)
        status = QLabel("已加载内置使用手册与系统提示词 · 默认 DeepSeek")
        status.setWordWrap(True)
        status.setStyleSheet("font-size:11px;color:#667085;padding:0 4px 4px")
        status.setToolTip(f"系统提示词已加载（{len(SYSTEM_PROMPT)} 字符）")
        layout.addWidget(status)

        self.messages = QTextBrowser()
        self.messages.setOpenExternalLinks(True)
        self.messages.setStyleSheet("QTextBrowser{background:#FAFAFA;border:1px solid #D9DEE5;}")
        self.messages.setHtml("<p><b>AI 助手</b></p><p>你好，我可以介绍 Echovault，并协助你使用素材库、识别、同步和命令行。</p>")
        layout.addWidget(self.messages, 1)

        self.input = QTextEdit()
        self.input.setPlaceholderText("输入问题，Ctrl+Enter 发送")
        self.input.setFixedHeight(80)
        layout.addWidget(self.input)
        actions = QHBoxLayout()
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self._clear)
        actions.addWidget(self.clear_button)
        actions.addStretch()
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._send()
            event.accept()
            return
        super().keyPressEvent(event)

    def _settings(self) -> AISettings:
        return AISettings(
            api_key=self.config.ai_model_api_key,
            base_url=self.config.ai_base_url,
            model=self.config.ai_model_name,
        )

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    def _append(self, speaker: str, message: str):
        self.messages.append(f"<p><b>{speaker}</b><br>{self._escape(message)}</p>")
        self.messages.verticalScrollBar().setValue(self.messages.verticalScrollBar().maximum())

    def _send(self):
        question = self.input.toPlainText().strip()
        if not question or self._worker is not None:
            return
        self.input.clear()
        self._append("你", question)
        self.send_button.setEnabled(False)
        self._worker = AIChatWorker(self._settings(), question, list(self._history), self)
        self._worker.completed.connect(lambda answer: self._on_answer(question, answer))
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_answer(self, question: str, answer: str):
        self._history.extend(({"role": "user", "content": question}, {"role": "assistant", "content": answer}))
        self._append("AI", answer)
        self._finish_request()

    def _on_error(self, message: str):
        self._append("AI", f"请求失败：{message}")
        self._finish_request()

    def _finish_request(self):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        self.send_button.setEnabled(True)

    def _clear(self):
        self._history.clear()
        self.messages.setHtml("<p><b>AI 助手</b></p><p>对话已清空，使用手册与系统提示词仍会在每次请求中发送。</p>")
