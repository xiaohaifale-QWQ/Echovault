from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QDialog,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from tests.qt_test_app import ensure_app, keep_widget
from ui.theme import (
    APP_STYLESHEET,
    apply_application_theme,
    polish_widget_tree,
)
from ui.title_bar import ApplicationTitleBar, FramelessResizeHandles


def test_theme_uses_rounded_light_controls_and_blue_primary_actions():
    assert "border-radius: 11px" in APP_STYLESHEET
    assert 'background: #2F7DD1' in APP_STYLESHEET
    assert 'QTabBar::tab:selected' in APP_STYLESHEET
    assert 'QScrollBar::handle:vertical' in APP_STYLESHEET
    assert "QSlider::handle:horizontal" in APP_STYLESHEET
    assert "QSlider::handle:vertical" in APP_STYLESHEET
    assert "border-radius: 11px" in APP_STYLESHEET
    assert "slider-handle.svg" in APP_STYLESHEET


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


def test_left_click_on_slider_track_jumps_to_clicked_position():
    app = ensure_app()
    apply_application_theme(app)
    slider = keep_widget(QSlider(Qt.Orientation.Horizontal))
    slider.setRange(0, 100)
    slider.setValue(0)
    slider.resize(200, 30)
    slider.show()
    app.processEvents()

    QTest.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        pos=QPoint(150, slider.height() // 2),
    )

    assert 70 <= slider.value() <= 80

    vertical = keep_widget(QSlider(Qt.Orientation.Vertical))
    vertical.setRange(0, 100)
    vertical.setValue(0)
    vertical.resize(30, 200)
    vertical.show()
    app.processEvents()

    QTest.mouseClick(
        vertical,
        Qt.MouseButton.LeftButton,
        pos=QPoint(vertical.width() // 2, 50),
    )

    assert 70 <= vertical.value() <= 80


def test_application_title_bar_exposes_standard_window_controls():
    ensure_app()
    window = keep_widget(QMainWindow())
    title_bar = ApplicationTitleBar(window, "琳琅乐府 Echovault")

    assert title_bar.height() == 38
    assert title_bar.title_label.text() == "琳琅乐府 Echovault"
    assert title_bar.minimize_button.toolTip() == "最小化"
    assert title_bar.maximize_button.toolTip() == "最大化"
    assert title_bar.close_button.toolTip() == "关闭"


def test_frameless_resize_handles_cover_every_window_edge():
    ensure_app()
    window = keep_widget(QMainWindow())
    window.resize(640, 480)
    resize_handles = FramelessResizeHandles(window)
    resize_handles.update_geometry()

    border = resize_handles.BORDER
    assert set(resize_handles.handles) == {
        "left",
        "right",
        "top",
        "bottom",
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
    }
    assert resize_handles.handles["left"].geometry().getRect() == (
        0,
        border,
        border,
        480 - 2 * border,
    )
    assert resize_handles.handles["bottom_right"].geometry().getRect() == (
        640 - border,
        480 - border,
        border,
        border,
    )
