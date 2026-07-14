from datetime import datetime

from PyQt6.QtCore import QDateTime
from PyQt6.QtWidgets import QApplication

from ui.library_panel import LibraryPanel


def _app():
    return QApplication.instance() or QApplication([])


def test_inline_video_calibration_uses_empty_right_time_as_no_calibration(tmp_path):
    _app()
    panel = LibraryPanel()
    video = {
        "name": "camera.mp4",
        "path": str(tmp_path / "camera.mp4"),
        "captured_at": datetime(2026, 7, 14, 10, 0, 0),
    }
    panel.set_video_materials(str(tmp_path), [video], 0)
    emitted = []
    panel.calibration_changed.connect(lambda *args: emitted.append(args))

    panel._emit_calibration()
    assert emitted[-1][2] is None
    assert panel.calibration_left.dateTime().toPyDateTime() == video["captured_at"]

    target = datetime(2026, 7, 14, 10, 5, 0)
    panel.calibration_right.setDateTime(QDateTime(target))
    panel._emit_calibration()
    assert emitted[-1][1] == video["captured_at"]
    assert emitted[-1][2] == target
