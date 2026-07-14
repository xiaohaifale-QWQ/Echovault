"""Material-library folder tree with separate music and video modes."""

import os

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class MaterialModeSwitch(QWidget):
    """Animated two-position slide switch used by the material library."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self._knob_position = 0.0
        self._animation = QPropertyAnimation(self, b"knob_position", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("滑动切换音乐模式与视频模式")

    def sizeHint(self):
        return QSize(68, 30)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked: bool):
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self._animation.stop()
        self._animation.setStartValue(self._knob_position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()
        self.toggled.emit(checked)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    @pyqtProperty(float)
    def knob_position(self):
        return self._knob_position

    @knob_position.setter
    def knob_position(self, value):
        self._knob_position = value
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(1, 3, -1, -3)
        painter.setBrush(QColor("#1976D2") if self._checked else QColor("#43A047"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 6
        x_range = track.width() - diameter - 6
        knob_x = track.x() + 3 + x_range * self._knob_position
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(knob_x), track.y() + 3, diameter, diameter)


class LibraryPanel(QWidget):
    folder_selected = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    directories_changed = pyqtSignal(str, object)
    calibrate_requested = pyqtSignal(str)
    aggregate_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "music"
        self._directories = {"music": [], "video": []}
        self._setup_ui()

    @property
    def mode(self) -> str:
        return self._mode

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel("素材库（音乐模式）")
        self.title.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        layout.addWidget(self.title)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemExpanded.connect(self._on_expanded)
        layout.addWidget(self.tree)

        self.btn_add = QPushButton("添加音乐文件夹")
        self.btn_add.clicked.connect(self._add_directory)
        layout.addWidget(self.btn_add)

        self.video_actions = QWidget()
        video_layout = QHBoxLayout(self.video_actions)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_calibrate = QPushButton("时间校准")
        self.btn_calibrate.clicked.connect(self._request_calibration)
        video_layout.addWidget(self.btn_calibrate)
        self.btn_aggregate = QPushButton("按时间汇总")
        self.btn_aggregate.clicked.connect(self._request_aggregate)
        video_layout.addWidget(self.btn_aggregate)
        layout.addWidget(self.video_actions)
        self.video_actions.setVisible(False)

        switch_layout = QHBoxLayout()
        self.music_mode_label = QLabel("音乐模式")
        switch_layout.addWidget(self.music_mode_label)
        self.mode_switch = MaterialModeSwitch()
        self.mode_switch.toggled.connect(self._switch_mode)
        switch_layout.addWidget(self.mode_switch)
        self.video_mode_label = QLabel("视频模式")
        switch_layout.addWidget(self.video_mode_label)
        switch_layout.addStretch()
        layout.addLayout(switch_layout)

        self.hint = QLabel("选择文件夹即可加载音频素材")
        self.hint.setStyleSheet("color:#888;font-size:10px;padding:4px")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint)

    def set_directories(self, music_dirs: list[str], video_dirs: list[str]):
        self._directories["music"] = self._existing_directories(music_dirs)
        self._directories["video"] = self._existing_directories(video_dirs)
        self._refresh_tree()

    def open_directory_picker(self):
        self._add_directory()

    def _existing_directories(self, directories: list[str]) -> list[str]:
        return [path for path in directories if os.path.isdir(path)]

    def _switch_mode(self, video_mode: bool):
        mode = "video" if video_mode else "music"
        if self._mode == mode:
            return
        self._mode = mode
        self._refresh_tree()
        self.mode_changed.emit(mode)
        if self._directories[mode]:
            self.folder_selected.emit(self._directories[mode][0])

    def _refresh_tree(self):
        self.tree.clear()
        is_video = self._mode == "video"
        self.title.setText(f"素材库（{'视频' if is_video else '音乐'}模式）")
        self.btn_add.setText(f"添加{'视频' if is_video else '音乐'}文件夹")
        self.video_actions.setVisible(is_video)
        hint = "选择文件夹即可加载视频素材" if is_video else "选择文件夹即可加载音频素材"
        self.hint.setText(hint)
        self.music_mode_label.setStyleSheet(
            "color:#43A047;font-weight:bold" if not is_video else "color:#888"
        )
        self.video_mode_label.setStyleSheet(
            "color:#1976D2;font-weight:bold" if is_video else "color:#888"
        )
        for path in self._directories[self._mode]:
            root = QTreeWidgetItem([os.path.basename(path) or path])
            root.setData(0, Qt.ItemDataRole.UserRole, path)
            root.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self.tree.addTopLevelItem(root)
            self._populate(root, path)
            root.setExpanded(True)

    def _add_directory(self):
        kind = "视频" if self._mode == "video" else "音乐"
        path = QFileDialog.getExistingDirectory(self, f"选择{kind}素材文件夹")
        if not path:
            return
        resolved = os.path.abspath(path)
        if resolved not in self._directories[self._mode]:
            self._directories[self._mode].append(resolved)
            self.directories_changed.emit(self._mode, list(self._directories[self._mode]))
        self._refresh_tree()
        self.folder_selected.emit(resolved)

    def _populate(self, parent, path, depth=1):
        if depth <= 0:
            return
        try:
            entries = sorted(os.scandir(path), key=lambda entry: entry.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir() and not entry.name.startswith("."):
                child = QTreeWidgetItem([entry.name])
                child.setData(0, Qt.ItemDataRole.UserRole, entry.path)
                try:
                    has_children = any(
                        item.is_dir() and not item.name.startswith(".")
                        for item in os.scandir(entry.path)
                    )
                except OSError:
                    has_children = False
                if has_children:
                    child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                    child.addChild(QTreeWidgetItem(["..."]))
                parent.addChild(child)

    def _on_expanded(self, item):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        while item.childCount() > 0 and item.child(0).text(0) == "...":
            item.removeChild(item.child(0))
        if item.childCount() == 0:
            self._populate(item, path)

    def _on_clicked(self, item, _column):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            self.folder_selected.emit(path)

    def _current_folder(self) -> str | None:
        item = self.tree.currentItem()
        path = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return path if path and os.path.isdir(path) else None

    def _request_calibration(self):
        path = self._current_folder()
        if path:
            self.calibrate_requested.emit(path)

    def _request_aggregate(self):
        path = self._current_folder()
        if path:
            self.aggregate_requested.emit(path)
