from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSplitter, QWidget

from tests.qt_test_app import ensure_app, keep_widget
from ui.motion import MotionController


def test_motion_controller_applies_final_state_without_visible_owner(monkeypatch):
    ensure_app()
    monkeypatch.delenv("ECHOVAULT_DISABLE_ANIMATIONS", raising=False)
    owner = keep_widget(QWidget())
    indicator = QFrame(owner)
    indicator.setGeometry(0, 0, 3, 20)
    motion = MotionController(owner)

    motion.animate_geometry("indicator", indicator, QRect(3, 40, 3, 32))

    assert indicator.geometry() == QRect(3, 40, 3, 32)


def test_splitter_motion_finishes_immediately_for_hidden_test_window():
    ensure_app()
    owner = keep_widget(QWidget())
    layout = QHBoxLayout(owner)
    splitter = QSplitter()
    content = QWidget()
    panel = QWidget()
    panel.setMinimumWidth(0)
    panel.setMaximumWidth(340)
    splitter.addWidget(content)
    splitter.addWidget(panel)
    layout.addWidget(splitter)
    panel.hide()
    motion = MotionController(owner)

    motion.animate_splitter_panel("drawer", splitter, panel, 340)
    assert panel.isVisibleTo(owner)
    assert splitter.sizes()[1] > 0

    motion.animate_splitter_panel("drawer", splitter, panel, 0)
    assert panel.isHidden()


def test_visible_motion_uses_short_interruptible_animation():
    app = ensure_app()
    owner = keep_widget(QWidget())
    owner.resize(400, 240)
    indicator = QFrame(owner)
    indicator.setGeometry(3, 10, 3, 24)
    label = QLabel("歌词与标签", owner)
    owner.show()
    app.processEvents()
    motion = MotionController(owner)

    target = QRect(3, 90, 3, 32)
    motion.animate_geometry("indicator", indicator, target)
    animation = motion._animations["indicator"]
    assert animation.duration() == 167
    animation.setCurrentTime(84)
    assert 10 < indicator.y() < 90
    animation.setCurrentTime(animation.duration())
    assert indicator.geometry() == target

    motion.fade_in("heading", (label,))
    assert label.graphicsEffect() is not None
    motion.fade_in("heading", (label,))
    fade = motion._animations["heading"]
    fade.setCurrentTime(fade.duration())
    assert label.graphicsEffect() is None
