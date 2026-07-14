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


def test_double_clicking_folder_opens_a_new_material_column(tmp_path):
    _app()
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "audio.mp3").write_bytes(b"")
    panel = LibraryPanel()
    panel.set_directories([str(root)], [])

    assert len(panel.folder_browser._columns) == 2
    assert panel.folder_browser._columns[1][1].count() == 1

    root_list = panel.folder_browser._columns[0][1]
    panel.folder_browser._open_item(root_list.item(0))
    child_list = panel.folder_browser._columns[1][1]
    panel.folder_browser._open_item(child_list.item(0))

    assert len(panel.folder_browser._columns) == 3
    assert panel.folder_browser.current_folder == str(child)
