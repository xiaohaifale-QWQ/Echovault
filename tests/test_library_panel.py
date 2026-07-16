from datetime import datetime

from PyQt6.QtCore import QDateTime

from tests.qt_test_app import ensure_app, keep_widget
from ui.library_panel import LibraryPanel


def test_inline_video_calibration_uses_empty_right_time_as_no_calibration(tmp_path):
    ensure_app()
    panel = keep_widget(LibraryPanel())
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
    app = ensure_app()
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "audio.mp3").write_bytes(b"")
    panel = keep_widget(LibraryPanel())
    panel.resize(600, 600)
    panel.set_directories([str(root)], [])
    panel.show()
    app.processEvents()

    assert len(panel.folder_browser._columns) == 2
    assert panel.folder_browser._columns[1][1].count() == 1
    assert panel.folder_browser._columns[0][1].parentWidget().height() > 0

    root_list = panel.folder_browser._columns[0][1]
    panel.folder_browser._open_item(root_list.item(0))
    child_list = panel.folder_browser._columns[1][1]
    panel.folder_browser._open_item(child_list.item(0))

    assert len(panel.folder_browser._columns) == 3
    assert panel.folder_browser.current_folder == str(child)

    selected = []
    panel.material_selected.connect(selected.append)
    panel.folder_browser._select_item(panel.folder_browser._columns[2][1].item(0))
    assert selected == [str(child / "audio.mp3")]


def test_hour_offset_fills_right_time_and_tracks_left_time(tmp_path):
    ensure_app()
    panel = keep_widget(LibraryPanel())
    recorded = datetime(2026, 7, 14, 10, 0, 0)
    panel.set_video_materials(
        str(tmp_path),
        [{"name": "camera.mp4", "path": str(tmp_path / "camera.mp4"), "captured_at": recorded}],
        0,
    )

    panel._set_target_from_offset(2.5)
    assert panel.calibration_right.dateTime().toPyDateTime() == datetime(2026, 7, 14, 12, 30, 0)

    panel.calibration_left.setDateTime(QDateTime(datetime(2026, 7, 14, 11, 0, 0)))
    panel._on_left_time_changed()
    assert panel.calibration_right.dateTime().toPyDateTime() == datetime(2026, 7, 14, 13, 30, 0)


def test_select_all_is_tracked_per_material_mode():
    ensure_app()
    panel = keep_widget(LibraryPanel())
    changes = []
    panel.select_all_changed.connect(lambda mode, selected: changes.append((mode, selected)))

    panel.select_all_check.setChecked(True)
    assert panel.select_all is True
    panel._switch_mode(True)
    assert panel.select_all is False
    panel.select_all_check.setChecked(True)
    panel._switch_mode(False)

    assert panel.select_all is True
    assert changes == [("music", True), ("video", True)]


def test_select_all_precedes_add_folder_and_mode_text_is_on_the_switch():
    ensure_app()
    panel = keep_widget(LibraryPanel())

    select_all_index = panel.folder_header.indexOf(panel.select_all_check)
    add_folder_index = panel.folder_header.indexOf(panel.btn_add)
    assert select_all_index < add_folder_index
    assert panel.mode_switch.minimumHeight() == 40


def test_removing_added_root_keeps_source_files_and_refreshes_roots(tmp_path):
    ensure_app()
    root = tmp_path / "music"
    root.mkdir()
    source = root / "song.mp3"
    source.write_bytes(b"audio")
    panel = keep_widget(LibraryPanel())
    changes = []
    selected = []
    panel.directories_changed.connect(lambda mode, directories: changes.append((mode, directories)))
    panel.folder_selected.connect(selected.append)
    panel.set_directories([str(root)], [])

    panel._remove_directory(str(root))

    assert source.is_file()
    assert changes == [("music", [])]
    assert selected[-1] == ""


def test_few_material_columns_expand_to_fill_the_available_width(tmp_path):
    app = ensure_app()
    root = tmp_path / "root"
    root.mkdir()
    (root / "song.mp3").write_bytes(b"")
    panel = keep_widget(LibraryPanel())
    panel.resize(900, 600)
    panel.set_directories([str(root)], [])
    panel.show()
    app.processEvents()

    columns = [listing.parentWidget() for _, listing in panel.folder_browser._columns]
    assert len(columns) == 2
    assert all(column.width() > 210 for column in columns)
