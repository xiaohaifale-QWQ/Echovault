from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QDialog,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from tests.qt_test_app import ensure_app, keep_widget
from ui.theme import (
    APP_STYLESHEET,
    apply_application_theme,
    polish_widget_tree,
)
from ui.title_bar import ApplicationTitleBar


def test_theme_uses_rounded_light_controls_and_blue_primary_actions():
    assert "border-radius: 11px" in APP_STYLESHEET
    assert 'background: #2F7DD1' in APP_STYLESHEET
    assert 'QTabBar::tab:selected' in APP_STYLESHEET
    assert 'QScrollBar::handle:vertical' in APP_STYLESHEET


def test_theme_normalizes_inline_button_styles_and_assigns_roles():
    app = ensure_app()
    apply_application_theme(app)
    dialog = keep_widget(QDialog())
    layout = QVBoxLayout(dialog)
    primary = QPushButton("开始处理")
    primary.setStyleSheet("QPushButton{border-radius:0;background:red}")
    secondary = QPushButton("打开目录")
    danger = QPushButton("清理缓存")
    score = QSpinBox()
    layout.addWidget(primary)
    layout.addWidget(secondary)
    layout.addWidget(danger)
    layout.addWidget(score)

    polish_widget_tree(dialog)

    assert primary.styleSheet() == ""
    assert primary.property("buttonRole") == "primary"
    assert secondary.property("buttonRole") == "secondary"
    assert danger.property("buttonRole") == "danger"
    assert all(button.minimumHeight() >= 32 for button in (primary, secondary, danger))
    assert score.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons


def test_application_title_bar_exposes_standard_window_controls():
    ensure_app()
    window = keep_widget(QMainWindow())
    title_bar = ApplicationTitleBar(window, "琳琅乐府 Echovault")

    assert title_bar.height() == 38
    assert title_bar.title_label.text() == "琳琅乐府 Echovault"
    assert title_bar.minimize_button.toolTip() == "最小化"
    assert title_bar.maximize_button.toolTip() == "最大化"
    assert title_bar.close_button.toolTip() == "关闭"
