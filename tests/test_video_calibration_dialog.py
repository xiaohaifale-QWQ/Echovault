from datetime import datetime

from PyQt6.QtCore import QDateTime
from PyQt6.QtWidgets import QApplication

from ui import video_calibration_dialog


def _app():
    return QApplication.instance() or QApplication([])


def test_dialog_reads_selected_video_and_supports_offset_or_actual_start(monkeypatch, tmp_path):
    _app()
    video = {
        "name": "camera.mp4",
        "path": str(tmp_path / "camera.mp4"),
        "captured_at": datetime(2026, 7, 14, 10, 0, 0),
        "timestamp_source": "视频元数据",
    }
    monkeypatch.setattr(video_calibration_dialog, "scan_videos", lambda _folder: [video])

    dialog = video_calibration_dialog.VideoCalibrationDialog(str(tmp_path), current_offset=15)

    assert dialog.recorded_label.text() == "2026-07-14 10:00:00"
    assert dialog.offset_seconds == 15
    dialog.start_radio.setChecked(True)
    dialog.actual_start.setDateTime(QDateTime(datetime(2026, 7, 14, 10, 1, 0)))
    assert dialog.offset_seconds == 60
