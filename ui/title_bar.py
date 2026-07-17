"""Lightweight application title bar used by the frameless main window."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStyle, QWidget


class ApplicationTitleBar(QWidget):
    """Codex-style light title bar with native window actions."""

    def __init__(self, window: QWidget, title: str):
        super().__init__(window)
        self._window = window
        self.setObjectName("applicationTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        self.app_mark = QLabel("E")
        self.app_mark.setObjectName("titleBarAppMark")
        self.app_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.app_mark.setFixedSize(20, 20)
        layout.addWidget(self.app_mark)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleBarTitle")
        self.title_label.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.minimize_button = self._window_button(
            QStyle.StandardPixmap.SP_TitleBarMinButton, "titleBarMinimize"
        )
        self.maximize_button = self._window_button(
            QStyle.StandardPixmap.SP_TitleBarMaxButton, "titleBarMaximize"
        )
        self.close_button = self._window_button(
            QStyle.StandardPixmap.SP_TitleBarCloseButton, "titleBarClose"
        )
        self.minimize_button.setToolTip("最小化")
        self.maximize_button.setToolTip("最大化")
        self.close_button.setToolTip("关闭")
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximized)
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)
        self.sync_window_state()

    def _window_button(
        self, icon: QStyle.StandardPixmap, name: str
    ) -> QPushButton:
        button = QPushButton()
        button.setObjectName(name)
        button.setIcon(self.style().standardIcon(icon))
        button.setIconSize(QSize(12, 12))
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(46, 38)
        return button

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_window_state()

    def sync_window_state(self) -> None:
        maximized = self._window.isMaximized()
        icon = (
            QStyle.StandardPixmap.SP_TitleBarNormalButton
            if maximized
            else QStyle.StandardPixmap.SP_TitleBarMaxButton
        )
        self.maximize_button.setIcon(self.style().standardIcon(icon))
        self.maximize_button.setToolTip("还原" if maximized else "最大化")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
