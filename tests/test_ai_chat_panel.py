from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from core.config import AppConfig
from tests.qt_test_app import ensure_app, keep_widget
from ui.ai_chat_panel import AIChatPanel


def test_enter_sends_and_ctrl_enter_inserts_a_newline():
    ensure_app()
    panel = keep_widget(AIChatPanel(AppConfig()))
    sent = []
    panel.input.send_requested.connect(lambda: sent.append(True))

    QApplication.sendEvent(
        panel.input,
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
    )
    QApplication.sendEvent(
        panel.input,
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier),
    )

    assert sent == [True]
    assert panel.input.toPlainText() == "\n"


def test_panel_selects_local_ai_settings():
    ensure_app()
    config = AppConfig(
        ai_provider="local",
        local_ai_base_url="http://127.0.0.1:1234/v1",
        local_ai_model_name="loaded-model",
    )
    panel = keep_widget(AIChatPanel(config))

    settings = panel._settings()

    assert settings.provider_name == "本地 AI"
    assert settings.base_url == "http://127.0.0.1:1234/v1"
    assert settings.model == "loaded-model"
    assert settings.requires_api_key is False
