"""Interactive calibration dialog for mapping video time to real time."""

from __future__ import annotations

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from core.video_library import calibration_offset_seconds, scan_videos


class VideoCalibrationDialog(QDialog):
    """Choose a reference video and define its calibrated start time."""

    def __init__(self, folder_path: str, current_offset: int = 0, parent=None):
        super().__init__(parent)
        self._folder_path = folder_path
        self._videos = scan_videos(folder_path)
        self.setWindowTitle("视频时间校准")
        self.setMinimumWidth(560)
        self._setup_ui(current_offset)

    @property
    def offset_seconds(self) -> int:
        if self.offset_radio.isChecked():
            return self.offset_spin.value()
        video = self.selected_video
        actual_start = self.actual_start.dateTime().toPyDateTime()
        return calibration_offset_seconds(video["captured_at"], actual_start)

    @property
    def selected_video(self) -> dict:
        return self.video_combo.currentData(Qt.ItemDataRole.UserRole)

    def _setup_ui(self, current_offset: int):
        layout = QVBoxLayout(self)
        intro = QLabel(
            "选择一个参考视频。左侧显示文件中读取的原始时间；右侧指定它应当对应的真实时间。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#555;padding:4px")
        layout.addWidget(intro)

        self.video_combo = QComboBox()
        for video in self._videos:
            stamp = video["captured_at"].strftime("%Y-%m-%d %H:%M:%S")
            self.video_combo.addItem(f"{video['name']}  ·  {stamp}", video)
        self.video_combo.currentIndexChanged.connect(self._update_video_details)
        layout.addWidget(self.video_combo)

        source_group = QGroupBox("读取到的视频时间")
        source_layout = QFormLayout(source_group)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.recorded_label = QLabel()
        self.source_label = QLabel()
        source_layout.addRow("视频文件：", self.path_label)
        source_layout.addRow("原始起始时间：", self.recorded_label)
        source_layout.addRow("时间来源：", self.source_label)
        layout.addWidget(source_group)

        target_group = QGroupBox("校准方式")
        target_layout = QFormLayout(target_group)
        self.offset_radio = QRadioButton("向后偏移秒数")
        self.start_radio = QRadioButton("指定该视频的真实起始时间")
        button_group = QButtonGroup(self)
        button_group.addButton(self.offset_radio)
        button_group.addButton(self.start_radio)
        self.offset_radio.setChecked(True)
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(-315_360_000, 315_360_000)
        self.offset_spin.setSuffix(" 秒（正数向后，负数向前）")
        self.offset_spin.setValue(current_offset)
        self.actual_start = QDateTimeEdit()
        self.actual_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.actual_start.setCalendarPopup(True)
        self.offset_radio.toggled.connect(self._update_calibration_controls)
        self.offset_spin.valueChanged.connect(self._update_preview)
        self.actual_start.dateTimeChanged.connect(self._update_preview)
        target_layout.addRow(self.offset_radio, self.offset_spin)
        target_layout.addRow(self.start_radio, self.actual_start)
        layout.addWidget(target_group)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("background:#F5F8FA;border:1px solid #DCE4EC;padding:8px")
        layout.addWidget(self.preview_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_video_details()
        self._update_calibration_controls()

    def _update_video_details(self):
        video = self.selected_video
        if not video:
            return
        recorded = video["captured_at"]
        self.path_label.setText(video["path"])
        self.recorded_label.setText(recorded.strftime("%Y-%m-%d %H:%M:%S"))
        self.source_label.setText(video["timestamp_source"])
        self.actual_start.setDateTime(QDateTime(recorded))
        self._update_preview()

    def _update_calibration_controls(self):
        self.offset_spin.setEnabled(self.offset_radio.isChecked())
        self.actual_start.setEnabled(self.start_radio.isChecked())
        self._update_preview()

    def _update_preview(self):
        video = self.selected_video
        if not video:
            return
        if self.offset_radio.isChecked():
            offset = self.offset_spin.value()
        else:
            offset = calibration_offset_seconds(
                video["captured_at"], self.actual_start.dateTime().toPyDateTime()
            )
        self.preview_label.setText(
            f"将对当前文件夹内所有视频使用 {offset:+d} 秒偏移；"
            "并更新“视频文字时间轴.csv”中的实际日期时间。"
        )
