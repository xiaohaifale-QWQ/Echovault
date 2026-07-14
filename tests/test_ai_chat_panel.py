from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from core.config import AppConfig
from ui.ai_chat_panel import AIChatPanel


def _app():
    return QApplication.instance() or QApplication([])


def test_enter_sends_and_ctrl_enter_inserts_a_newline():
    _app()
    panel = AIChatPanel(AppConfig())
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
