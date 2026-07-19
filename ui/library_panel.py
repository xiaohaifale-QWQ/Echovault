"""Two-mode material-library explorer and inline video-time calibration."""

from __future__ import annotations

import os
from datetime import timedelta

from PyQt6.QtCore import (
    QDate,
    QDateTime,
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTime,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.folder_columns import FolderColumnsBrowser


class MaterialModeSwitch(QWidget):
    """Compact segmented switch for music and video libraries."""

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
        self.setMinimumHeight(40)
        self.setMaximumHeight(40)

    def sizeHint(self):
        return QSize(220, 40)

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
        track = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QColor("#D3DCE7"))
        painter.setBrush(QColor("#EEF3F8"))
        painter.drawRoundedRect(track, 10, 10)

        half_width = track.width() // 2
        knob_width = max(32, half_width - 4)
        knob_x = track.x() + 2 + (track.width() - knob_width - 4) * self._knob_position
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QColor("#9DC0E3"))
        painter.drawRoundedRect(
            int(knob_x),
            track.y() + 2,
            knob_width,
            track.height() - 4,
            8,
            8,
        )

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        left_rect = track.adjusted(0, 0, -half_width, 0)
        right_rect = track.adjusted(half_width, 0, 0, 0)
        painter.setPen(QColor("#1F6FBB") if not self._checked else QColor("#667386"))
        painter.drawText(left_rect, Qt.AlignmentFlag.AlignCenter, "音乐模式")
        painter.setPen(QColor("#1F6FBB") if self._checked else QColor("#667386"))
        painter.drawText(right_rect, Qt.AlignmentFlag.AlignCenter, "视频模式")


class TimeOffsetDash(QLabel):
    """A dash that differentiates a normal click from a double-click."""

    clicked = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("—", parent)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(220)
        self._click_timer.timeout.connect(self.clicked)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.start()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LibraryPanel(QWidget):
    folder_selected = pyqtSignal(str)
    folders_selected = pyqtSignal(object)
    material_selected = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    directories_changed = pyqtSignal(str, object)
    calibration_changed = pyqtSignal(str, object, object)
    aggregate_requested = pyqtSignal(str)
    export_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "music"
        self._directories = {"music": [], "video": []}
        self._calibration_folder = ""
        self._videos = []
        self._current_offset = 0
        self._offset_hours: float | None = None
        self._setup_ui()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def select_all(self) -> bool:
        return len(self.folder_browser.selected_folders) > 1

    def set_select_all_modes(self, music_selected: bool, video_selected: bool):
        """Retained for configuration compatibility; selection now lives in the tree."""

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.folder_header = header
        self.title = QLabel("素材文件夹")
        self.title.setStyleSheet("font-weight:700;font-size:14px;padding:2px 0")
        header.addWidget(self.title)
        self.mode_switch = MaterialModeSwitch()
        self.mode_switch.setFixedWidth(220)
        self.mode_switch.toggled.connect(self._switch_mode)
        header.addWidget(self.mode_switch)
        header.addStretch()
        self.btn_add = QPushButton("＋")
        self.btn_add.setObjectName("addMaterialFolderButton")
        self.btn_add.setFixedSize(36, 36)
        self.btn_add.setToolTip("添加素材文件夹")
        self.btn_add.clicked.connect(self._add_directory)
        header.addWidget(self.btn_add)
        layout.addLayout(header)

        self.folder_browser = FolderColumnsBrowser()
        self.folder_browser.folder_selected.connect(self.folder_selected)
        self.folder_browser.folders_selected.connect(self.folders_selected)
        self.folder_browser.material_selected.connect(self.material_selected)
        self.folder_browser.root_removal_requested.connect(self._remove_directory)
        layout.addWidget(self.folder_browser, 1)

        self.video_controls = QGroupBox("视频时间校准")
        video_layout = QVBoxLayout(self.video_controls)
        video_layout.setSpacing(8)
        reference_row = QHBoxLayout()
        reference_row.addWidget(QLabel("参考视频"))
        self.reference_combo = QComboBox()
        self.reference_combo.currentIndexChanged.connect(self._on_reference_changed)
        reference_row.addWidget(self.reference_combo, 1)
        video_layout.addLayout(reference_row)

        calibration_box = QFrame()
        calibration_box.setStyleSheet(
            "QFrame{background:#F7F9FC;border:1px solid #E0E6ED;border-radius:8px}"
        )
        calibration_layout = QFormLayout(calibration_box)
        calibration_layout.setContentsMargins(8, 8, 8, 8)
        time_row = QHBoxLayout()
        self.calibration_left = QDateTimeEdit()
        self.calibration_left.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.calibration_left.setCalendarPopup(False)
        self.calibration_left.setReadOnly(False)
        self.calibration_left.editingFinished.connect(self._on_left_time_changed)
        time_row.addWidget(self.calibration_left)
        dash = QLabel("—")
        dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dash.setStyleSheet("font-size:18px;color:#667")
        time_row.addWidget(dash)
        dash.setVisible(False)
        time_row.removeWidget(dash)
        self.offset_dash = TimeOffsetDash()
        self.offset_dash.setToolTip("单击选择常用偏移；双击输入向后推的小时数")
        self.offset_dash.setStyleSheet("font-size:18px;color:#667;padding:0 5px")
        self.offset_dash.clicked.connect(self._choose_hour_offset)
        self.offset_dash.double_clicked.connect(self._input_hour_offset)
        time_row.addWidget(self.offset_dash)
        self.calibration_right = QDateTimeEdit()
        self.calibration_right.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.calibration_right.setCalendarPopup(False)
        self.calibration_right.setReadOnly(False)
        self.calibration_right.setMinimumDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0, 0)))
        self.calibration_right.setSpecialValueText("不校准")
        self.calibration_right.editingFinished.connect(self._on_right_time_changed)
        time_row.addWidget(self.calibration_right)
        calibration_layout.addRow("原始时间 → 真实时间", time_row)
        video_layout.addWidget(calibration_box)

        action_row = QHBoxLayout()
        self.btn_aggregate = QPushButton("汇总")
        self.btn_aggregate.clicked.connect(self._request_aggregate)
        action_row.addWidget(self.btn_aggregate)
        self.btn_export = QPushButton("导出")
        self.btn_export.clicked.connect(self._request_export)
        action_row.addWidget(self.btn_export)
        action_row.addStretch()
        video_layout.addLayout(action_row)
        layout.addWidget(self.video_controls)
        self.video_controls.setVisible(False)

    def set_directories(self, music_dirs: list[str], video_dirs: list[str]):
        self._directories["music"] = self._existing_directories(music_dirs)
        self._directories["video"] = self._existing_directories(video_dirs)
        self._refresh_folders()

    def set_video_materials(self, folder_path: str, videos: list[dict], offset_seconds: int):
        self._calibration_folder = folder_path
        self._videos = videos
        self._current_offset = offset_seconds
        self.reference_combo.blockSignals(True)
        self.reference_combo.clear()
        for video in videos:
            timestamp = video["captured_at"].strftime("%Y-%m-%d %H:%M:%S")
            self.reference_combo.addItem(f"{video['name']} · {timestamp}", video)
        self.reference_combo.blockSignals(False)
        self._on_reference_changed()

    def clear_video_materials(self):
        self._calibration_folder = ""
        self._videos = []
        self.reference_combo.clear()

    def open_directory_picker(self):
        self._add_directory()

    def _existing_directories(self, directories: list[str]) -> list[str]:
        return [path for path in directories if os.path.isdir(path)]

    def _switch_mode(self, video_mode: bool):
        mode = "video" if video_mode else "music"
        if self._mode == mode:
            return
        self._mode = mode
        self._refresh_folders()
        self.mode_changed.emit(mode)
        if self._directories[mode]:
            self.folders_selected.emit([self._directories[mode][0]])

    def _refresh_folders(self):
        is_video = self._mode == "video"
        self.title.setText(f"{'视频' if is_video else '音乐'}素材文件夹")
        self.btn_add.setToolTip(f"添加{'视频' if is_video else '音乐'}素材文件夹")
        self.video_controls.setVisible(is_video)
        self.folder_browser.set_roots(self._directories[self._mode])

    def _add_directory(self):
        kind = "视频" if self._mode == "video" else "音乐"
        path = QFileDialog.getExistingDirectory(self, f"选择{kind}素材文件夹")
        if not path:
            return
        resolved = os.path.abspath(path)
        if resolved not in self._directories[self._mode]:
            self._directories[self._mode].append(resolved)
            self.directories_changed.emit(self._mode, list(self._directories[self._mode]))
        self._refresh_folders()
        self.folders_selected.emit([resolved])

    def _remove_directory(self, folder_path: str):
        """Remove only an added root; it never touches the user's source files."""
        directories = self._directories[self._mode]
        if folder_path not in directories:
            return
        directories.remove(folder_path)
        self.directories_changed.emit(self._mode, list(directories))
        self._refresh_folders()
        self.folders_selected.emit([directories[0]] if directories else [])

    def _on_reference_changed(self):
        video = self.reference_combo.currentData(Qt.ItemDataRole.UserRole)
        if not video:
            return
        recorded = video["captured_at"]
        self.calibration_left.blockSignals(True)
        self.calibration_right.blockSignals(True)
        self.calibration_left.setDateTime(QDateTime(recorded))
        minimum = self.calibration_right.minimumDateTime()
        if self._current_offset:
            adjusted = recorded + timedelta(seconds=self._current_offset)
            self.calibration_right.setDateTime(QDateTime(adjusted))
            self._offset_hours = self._current_offset / 3600
        else:
            self.calibration_right.setDateTime(minimum)
            self._offset_hours = None
        self.calibration_left.blockSignals(False)
        self.calibration_right.blockSignals(False)

    def _on_left_time_changed(self):
        if self._offset_hours is not None:
            self._set_target_from_offset(self._offset_hours, emit=False)
        self._emit_calibration()

    def _on_right_time_changed(self):
        target = self.calibration_right.dateTime()
        if target == self.calibration_right.minimumDateTime():
            self._offset_hours = None
        else:
            self._offset_hours = self.calibration_left.dateTime().secsTo(target) / 3600
        self._emit_calibration()

    def _choose_hour_offset(self):
        menu = QMenu(self)
        for hours in (1, 2, 6, 12, 24):
            action = menu.addAction(f"向后推 {hours} 小时")
            action.triggered.connect(
                lambda _checked=False, selected_hours=hours: self._set_target_from_offset(
                    selected_hours
                )
            )
        menu.addSeparator()
        custom_action = menu.addAction("自定义小时数…")
        custom_action.triggered.connect(self._input_hour_offset)
        menu.exec(self.offset_dash.mapToGlobal(self.offset_dash.rect().bottomLeft()))

    def _input_hour_offset(self):
        value, accepted = QInputDialog.getDouble(
            self,
            "时间偏差校准",
            "向后推多少小时？负数表示向前推：",
            self._offset_hours or 0.0,
            -24 * 365,
            24 * 365,
            2,
        )
        if accepted:
            self._set_target_from_offset(value)

    def _set_target_from_offset(self, hours: float, *, emit: bool = True):
        self._offset_hours = hours
        source = self.calibration_left.dateTime()
        target = source.addSecs(round(hours * 3600))
        self.calibration_right.blockSignals(True)
        self.calibration_right.setDateTime(target)
        self.calibration_right.blockSignals(False)
        if emit:
            self._emit_calibration()

    def _emit_calibration(self):
        if not self._calibration_folder or self.reference_combo.currentIndex() < 0:
            return
        source = self.calibration_left.dateTime().toPyDateTime()
        target_value = self.calibration_right.dateTime()
        target = (
            None
            if target_value == self.calibration_right.minimumDateTime()
            else target_value.toPyDateTime()
        )
        self.calibration_changed.emit(self._calibration_folder, source, target)

    def _request_aggregate(self):
        if self._calibration_folder:
            self.aggregate_requested.emit(self._calibration_folder)

    def _request_export(self):
        if self._calibration_folder:
            self.export_requested.emit(self._calibration_folder)
