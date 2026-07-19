"""Application-wide Echovault visual theme and dynamic widget polishing."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QProxyStyle,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QWidget,
)


class ClickJumpSliderStyle(QProxyStyle):
    """Make a left click on any slider track set the absolute position."""

    def styleHint(self, hint, option=None, widget=None, return_data=None):
        if hint == QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
            return Qt.MouseButton.LeftButton.value
        return super().styleHint(hint, option, widget, return_data)

PRIMARY_OBJECT_NAMES = {
    "primaryAction",
}
PRIMARY_TEXT_PREFIXES = (
    "开始",
    "▶ 开始处理",
    "开始录音",
    "开始批量",
    "执行：",
    "执行文件夹同步",
    "发送选中的",
    "识别歌词",
    "识别视频音频",
    "重新识别",
    "确定",
    "保存",
    "应用",
    "下载",
    "使用",
    "导出",
    "应用处理",
    "保存调音结果",
    "开启接收",
    "自动配置本地识别",
)
DANGER_TEXT_PREFIXES = (
    "删除",
    "清理缓存",
    "停止",
    "取消下载",
    "关闭接收",
)

APP_STYLESHEET = """
QWidget {
    color: #17233A;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #F6F8FB;
}
QWidget#applicationTitleBar {
    background: #FFFFFF;
    border-bottom: 1px solid #E2E7EE;
}
QLabel#titleBarAppMark {
    background: #E8F2FD;
    color: #246FB8;
    border: 1px solid #BCD6F0;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#titleBarTitle {
    color: #26354A;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#titleBarMinimize,
QPushButton#titleBarMaximize,
QPushButton#titleBarClose {
    background: transparent;
    color: #354052;
    border: none;
    border-radius: 0;
    min-height: 38px;
    max-height: 38px;
    padding: 0;
    font-family: "Segoe UI Symbol", "Segoe UI";
    font-size: 15px;
    font-weight: 400;
}
QPushButton#titleBarMinimize:hover,
QPushButton#titleBarMaximize:hover {
    background: #EEF1F5;
    color: #17233A;
    border: none;
}
QPushButton#titleBarClose:hover {
    background: #C42B1C;
    color: #FFFFFF;
    border: none;
}
QToolTip {
    background: #17233A;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 6px 8px;
}
QMenuBar {
    background: #FFFFFF;
    color: #26354A;
    border-bottom: 1px solid #E2E7EE;
    padding: 3px 8px;
    spacing: 4px;
}
QMenuBar::item {
    background: transparent;
    border-radius: 7px;
    padding: 7px 11px;
}
QMenuBar::item:selected {
    background: #EAF2FC;
    color: #1F6FBB;
}
QMenu {
    background: #FFFFFF;
    border: 1px solid #DCE3EB;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    border-radius: 6px;
    padding: 8px 26px 8px 12px;
}
QMenu::item:selected {
    background: #EAF2FC;
    color: #1F6FBB;
}
QStatusBar {
    background: #FFFFFF;
    color: #657184;
    border-top: 1px solid #E2E7EE;
}
QPushButton#statusStopButton {
    background: #FFF7F7;
    color: #B54747;
    border: 1px solid #E7B8B8;
    border-radius: 6px;
    min-width: 58px;
    min-height: 22px;
    max-height: 22px;
    padding: 0 10px;
    font-size: 11px;
}
QPushButton#statusStopButton:hover {
    background: #FCEAEA;
    color: #9F3535;
    border-color: #D99090;
}
QPushButton#statusStopButton:disabled {
    background: #F4F5F7;
    color: #A0A8B3;
    border-color: #E0E4E9;
}
QPushButton#modelActionButton {
    min-height: 26px;
    max-height: 26px;
    min-width: 68px;
    margin: 5px 4px;
    padding: 0 10px;
    border-radius: 6px;
}
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #E1E6ED;
}
QGroupBox {
    background: #FFFFFF;
    border: 1px solid #DCE3EB;
    border-radius: 11px;
    margin-top: 13px;
    padding: 14px 11px 11px 11px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #334155;
    background: #FFFFFF;
}
QGroupBox:checkable::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #B7C2D0;
    border-radius: 5px;
    background: #FFFFFF;
}
QGroupBox:checkable::indicator:checked {
    background: #2F7DD1;
    border-color: #2F7DD1;
}
QPushButton, QToolButton {
    background: #FFFFFF;
    color: #2B3A50;
    border: 1px solid #C9D3DF;
    border-radius: 8px;
    min-height: 30px;
    padding: 5px 13px;
    font-weight: 500;
}
QPushButton:hover, QToolButton:hover {
    background: #F2F6FB;
    border-color: #91B6DB;
    color: #1F6FBB;
}
QPushButton:pressed, QToolButton:pressed {
    background: #E5EEF9;
    border-color: #6B9DCE;
}
QPushButton:disabled, QToolButton:disabled {
    background: #F0F2F5;
    color: #A0A8B3;
    border-color: #E0E4E9;
}
QPushButton[buttonRole="primary"] {
    background: #2F7DD1;
    color: #FFFFFF;
    border: 1px solid #2F7DD1;
    font-weight: 700;
}
QPushButton[buttonRole="primary"]:hover {
    background: #236DBB;
    border-color: #236DBB;
    color: #FFFFFF;
}
QPushButton[buttonRole="primary"]:pressed {
    background: #195C9F;
    border-color: #195C9F;
}
QPushButton[buttonRole="danger"] {
    background: #FFF7F7;
    color: #B54747;
    border-color: #E7B8B8;
}
QPushButton[buttonRole="danger"]:hover {
    background: #FCEAEA;
    color: #9F3535;
    border-color: #D99191;
}
QPushButton[buttonRole="ghost"] {
    background: transparent;
    border-color: transparent;
    color: #5F6C7D;
}
QPushButton[buttonRole="ghost"]:hover {
    background: #EDF2F8;
    color: #1F6FBB;
}
QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser,
QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QKeySequenceEdit {
    background: #FFFFFF;
    color: #243147;
    border: 1px solid #CDD6E1;
    border-radius: 8px;
    padding: 6px 9px;
    selection-background-color: #BFD9F4;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus {
    border: 1px solid #4C91D5;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #F0F2F5;
    color: #9AA3AF;
}
QComboBox {
    min-height: 28px;
    padding-right: 26px;
}
QComboBox::drop-down {
    width: 25px;
    border: none;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #D7DEE8;
    border-radius: 8px;
    selection-background-color: #E7F1FC;
    selection-color: #1F6FBB;
    outline: none;
    padding: 4px;
}
QCheckBox, QRadioButton {
    spacing: 7px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 17px;
    height: 17px;
    background: #FFFFFF;
    border: 1px solid #B8C3D1;
}
QCheckBox::indicator {
    border-radius: 5px;
}
QRadioButton::indicator {
    border-radius: 9px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: #2F7DD1;
    border-color: #2F7DD1;
}
QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #DCE3EB;
    border-radius: 11px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #637083;
    border: 1px solid transparent;
    border-radius: 8px;
    min-height: 28px;
    padding: 7px 16px;
    margin: 3px 2px;
}
QTabBar::tab:hover {
    background: #F0F4F9;
    color: #2E5F91;
}
QTabBar::tab:selected {
    background: #E7F1FC;
    color: #1F6FBB;
    border-color: #B9D2EC;
    font-weight: 700;
}
QTableView, QTableWidget, QListView, QListWidget, QTreeView {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #DCE3EB;
    border-radius: 10px;
    gridline-color: #EDF0F4;
    selection-background-color: #DCECFB;
    selection-color: #163F69;
    outline: none;
}
QHeaderView::section {
    background: #F2F5F9;
    color: #526073;
    border: none;
    border-bottom: 1px solid #DCE3EB;
    border-right: 1px solid #E4E8EE;
    padding: 7px 8px;
    font-weight: 600;
}
QProgressBar {
    background: #E8EDF3;
    border: none;
    border-radius: 7px;
    min-height: 13px;
    color: #455468;
    text-align: center;
}
QProgressBar::chunk {
    background: #2F7DD1;
    border-radius: 7px;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #DCE3EB;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #77AEE2;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 15px;
    height: 15px;
    margin: -5px 0;
    background: #FFFFFF;
    border: 2px solid #2F7DD1;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #EAF3FC;
}
QSlider::groove:vertical {
    width: 5px;
    background: #DCE3EB;
    border-radius: 2px;
}
QSlider::sub-page:vertical {
    background: #77AEE2;
    border-radius: 2px;
}
QSlider::handle:vertical {
    width: 15px;
    height: 15px;
    margin: 0 -5px;
    background: #FFFFFF;
    border: 2px solid #2F7DD1;
    border-radius: 8px;
}
QSlider::handle:vertical:hover {
    background: #EAF3FC;
}
QSplitter::handle {
    background: transparent;
    width: 6px;
    height: 6px;
}
QSplitter::handle:hover {
    background: #D8E6F5;
    border-radius: 3px;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: #C3CCD7;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #9FAFC0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 3px;
}
QScrollBar::handle:horizontal {
    background: #C3CCD7;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: #9FAFC0;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
    border: none;
}
"""


def _button_role(button: QPushButton) -> str:
    if button.objectName() in PRIMARY_OBJECT_NAMES:
        return "primary"
    text = button.text().replace("&", "").strip()
    if text.startswith(DANGER_TEXT_PREFIXES):
        return "danger"
    if text.startswith(("←", "返回")):
        return "ghost"
    if text.startswith(PRIMARY_TEXT_PREFIXES):
        return "primary"
    return "secondary"


def polish_widget_tree(root: QWidget) -> None:
    """Normalize inline-styled controls so the application theme stays consistent."""
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if isinstance(widget, QPushButton):
            if widget.objectName() == "statusStopButton":
                widget.setProperty("buttonRole", "danger")
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
                widget.setFixedHeight(24)
                widget.setMinimumWidth(58)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                continue
            if widget.objectName() == "modelActionButton":
                widget.setProperty("buttonRole", _button_role(widget))
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                continue
            if widget.objectName() not in {
                "workspaceNavigationButton",
                "audioToolButton",
            } and not widget.objectName().startswith("titleBar"):
                widget.setStyleSheet("")
                widget.setProperty("buttonRole", _button_role(widget))
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
                if widget.minimumHeight() < 32:
                    widget.setMinimumHeight(32)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        elif isinstance(widget, QAbstractButton):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        elif isinstance(widget, QSlider):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        elif isinstance(widget, (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox)):
            if widget.minimumHeight() < 32:
                widget.setMinimumHeight(32)
            if isinstance(widget, QAbstractSpinBox):
                widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)


def apply_application_theme(app: QApplication) -> None:
    """Install the global visual system before the main window is constructed."""
    if not isinstance(app.style(), ClickJumpSliderStyle):
        app.setStyle(ClickJumpSliderStyle(app.style()))
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(APP_STYLESHEET)
