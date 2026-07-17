"""Small, interruptible UI transitions for the desktop shell."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QVariantAnimation,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QSplitter, QWidget

FADE_DURATION_MS = 83
DIRECT_DURATION_MS = 167
NORMAL_DURATION_MS = 250


def animations_enabled() -> bool:
    """Allow deterministic screenshots and an explicit reduced-motion override."""
    disabled = os.environ.get("ECHOVAULT_DISABLE_ANIMATIONS", "").strip().casefold()
    return disabled not in {"1", "true", "yes", "on"}


class MotionController(QObject):
    """Own active animations so repeated clicks replace, rather than stack, motion."""

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.owner = owner
        self.enabled = animations_enabled()
        self._animations: dict[str, QObject] = {}
        self._fade_widgets: dict[str, list[QWidget]] = {}

    def _should_animate(self) -> bool:
        return self.enabled and self.owner.isVisible()

    def _stop(self, key: str) -> None:
        animation = self._animations.pop(key, None)
        if animation is not None and hasattr(animation, "stop"):
            animation.stop()
        for widget in self._fade_widgets.pop(key, []):
            widget.setGraphicsEffect(None)

    def animate_geometry(
        self,
        key: str,
        widget: QWidget,
        target: QRect,
        duration: int = DIRECT_DURATION_MS,
    ) -> None:
        self._stop(key)
        if not self._should_animate() or widget.geometry() == target:
            widget.setGeometry(target)
            return

        animation = QPropertyAnimation(widget, b"geometry", self)
        animation.setStartValue(widget.geometry())
        animation.setEndValue(target)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animations[key] = animation
        animation.finished.connect(lambda: self._animations.pop(key, None))
        animation.start()

    def fade_in(
        self,
        key: str,
        widgets: Iterable[QWidget],
        duration: int = FADE_DURATION_MS,
    ) -> None:
        self._stop(key)
        targets = [widget for widget in widgets if widget is not None]
        if not self._should_animate() or not targets:
            return

        group = QParallelAnimationGroup(self)
        self._fade_widgets[key] = targets
        for widget in targets:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.35)
            widget.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setStartValue(0.35)
            animation.setEndValue(1.0)
            animation.setDuration(duration)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(animation)

        def cleanup() -> None:
            for widget in self._fade_widgets.pop(key, []):
                widget.setGraphicsEffect(None)
            self._animations.pop(key, None)

        group.finished.connect(cleanup)
        self._animations[key] = group
        group.start()

    def animate_splitter_panel(
        self,
        key: str,
        splitter: QSplitter,
        panel: QWidget,
        target_width: int,
        duration: int = DIRECT_DURATION_MS,
        finished: Callable[[], None] | None = None,
    ) -> None:
        self._stop(key)
        target_width = max(0, int(target_width))
        sizes = splitter.sizes()
        current_width = sizes[1] if len(sizes) > 1 and panel.isVisible() else 0
        total_width = max(sum(sizes), splitter.width(), self.owner.width(), 1)

        def apply_width(value) -> None:
            width = max(0, min(int(value), target_width or current_width))
            splitter.setSizes([max(1, total_width - width), width])

        def complete() -> None:
            splitter.setSizes([max(1, total_width - target_width), target_width])
            if target_width == 0:
                panel.setVisible(False)
            self._animations.pop(key, None)
            if finished is not None:
                finished()

        if target_width > 0:
            panel.setVisible(True)
            if current_width == 0:
                current_width = 1
                splitter.setSizes([max(1, total_width - 1), 1])

        if not self._should_animate() or current_width == target_width:
            complete()
            return

        animation = QVariantAnimation(self)
        animation.setStartValue(current_width)
        animation.setEndValue(target_width)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(apply_width)
        animation.finished.connect(complete)
        self._animations[key] = animation
        animation.start()

