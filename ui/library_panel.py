"""Two-mode material-library folder tree and inline video-time calibration."""

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
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ui.folder_columns import FolderColumnsBrowser


class MaterialModeSwitch(QWidget):
    """Full-width square, neutral-grey slide switch for the two library modes."""

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
        self.setMinimumHeight(54)

    def sizeHint(self):
        return QSize(260, 54)

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
        track = self.rect().adjusted(2, 4, -2, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#B8BEC6"))
        painter.drawRect(track)

        half_width = track.width() // 2
        knob_width = max(32, half_width - 6)
        knob_x = track.x() + 3 + (track.width() - knob_width - 6) * self._knob_position
        painter.setBrush(QColor("#767E87"))
        painter.setPen(QColor("#626A73"))
        painter.drawRect(int(knob_x), track.y() + 3, knob_width, track.height() - 6)

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        left_rect = track.adjusted(0, 0, -half_width, 0)
        right_rect = track.adjusted(half_width, 0, 0, 0)
        painter.setPen(QColor("#FFFFFF") if not self._checked else QColor("#3D4650"))
        painter.drawText(left_rect, Qt.AlignmentFlag.AlignCenter, "音乐模式")
        painter.setPen(QColor("#FFFFFF") if self._checked else QColor("#3D4650"))
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
    material_selected = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    select_all_changed = pyqtSignal(str, bool)
    directories_changed = pyqtSignal(str, object)
    calibration_changed = pyqtSignal(str, object, object)
    aggregate_requested = pyqtSignal(str)
    export_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "music"
        self._directories = {"music": [], "video": []}
        self._select_all = {"music": False, "video": False}
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
        return self._select_all[self._mode]

    def set_select_all_modes(self, music_selected: bool, video_selected: bool):
        self._select_all = {"music": bool(music_selected), "video": bool(video_selected)}
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(self._select_all[self._mode])
        self.select_all_check.blockSignals(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        splitter = QSplitter(Qt.Orientation.Vertical)

        folder_section = QWidget()
        folder_layout = QVBoxLayout(folder_section)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.folder_header = header
        self.title = QLabel("素材库（音乐模式）")
        self.title.setStyleSheet("font-weight:bold;font-size:13px;padding:4px")
        header.addWidget(self.title)
        header.addStretch()
        self.select_all_check = QCheckBox("全选")
        self.select_all_check.setToolTip("勾选后，详情页显示当前模式下所有素材文件夹的内容")
        self.select_all_check.toggled.connect(self._on_select_all_toggled)
        header.addWidget(self.select_all_check)
        self.btn_add = QPushButton("添加文件夹")
        self.btn_add.clicked.connect(self._add_directory)
        header.addWidget(self.btn_add)
        folder_layout.addLayout(header)
        self.folder_browser = FolderColumnsBrowser()
        self.folder_browser.folder_selected.connect(self.folder_selected)
        self.folder_browser.material_selected.connect(self.material_selected)
        folder_layout.addWidget(self.folder_browser)
        splitter.addWidget(folder_section)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(4, 4, 4, 4)
        self.mode_switch = MaterialModeSwitch()
        self.mode_switch.toggled.connect(self._switch_mode)
        controls_layout.addWidget(self.mode_switch)

        self.video_controls = QWidget()
        video_layout = QVBoxLayout(self.video_controls)
        video_layout.setContentsMargins(0, 6, 0, 0)
        self.reference_combo = QComboBox()
        self.reference_combo.currentIndexChanged.connect(self._on_reference_changed)
        video_layout.addWidget(QLabel("校准参考视频"))
        video_layout.addWidget(self.reference_combo)

        calibration_box = QFrame()
        calibration_box.setStyleSheet(
            "QFrame{background:#F6F8FA;border:1px solid #DCE4EC;border-radius:5px}"
        )
        calibration_layout = QFormLayout(calibration_box)
        calibration_layout.setContentsMargins(8, 8, 8, 8)
        calibration_layout.addRow(QLabel("时间校准"), QLabel("左侧原始时间 — 右侧真实时间"))
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
        calibration_layout.addRow(time_row)
        video_layout.addWidget(calibration_box)

        action_row = QHBoxLayout()
        self.btn_aggregate = QPushButton("汇总")
        self.btn_aggregate.clicked.connect(self._request_aggregate)
        action_row.addWidget(self.btn_aggregate)
        self.btn_export = QPushButton("导出")
        self.btn_export.clicked.connect(self._request_export)
        action_row.addWidget(self.btn_export)
        video_layout.addLayout(action_row)
        video_layout.addStretch()
        controls_layout.addWidget(self.video_controls)
        controls_layout.addStretch()
        splitter.addWidget(controls)
        splitter.setSizes([340, 340])
        layout.addWidget(splitter)
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
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(self._select_all[mode])
        self.select_all_check.blockSignals(False)
        self._refresh_folders()
        self.mode_changed.emit(mode)
        if self._directories[mode]:
            self.folder_selected.emit(self._directories[mode][0])

    def _on_select_all_toggled(self, checked: bool):
        self._select_all[self._mode] = checked
        self.select_all_changed.emit(self._mode, checked)

    def _refresh_folders(self):
        is_video = self._mode == "video"
        self.title.setText(f"素材库（{'视频' if is_video else '音乐'}模式）")
        self.btn_add.setText(f"添加{'视频' if is_video else '音乐'}文件夹")
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
        self.folder_selected.emit(resolved)

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
