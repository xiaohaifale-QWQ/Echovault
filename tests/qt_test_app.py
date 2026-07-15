"""Keep one QApplication wrapper alive for direct Qt widget tests."""

from PyQt6.QtWidgets import QApplication

_APP = None
_WIDGETS = []


def ensure_app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def keep_widget(widget):
    """Prevent PyQt wrappers from being destroyed mid-session during processEvents()."""
    _WIDGETS.append(widget)
    return widget
