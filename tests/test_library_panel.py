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


def test_folder_browser_uses_one_windows_style_tree_and_opens_subfolders(tmp_path):
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

    tree = panel.folder_browser.tree
    assert tree.columnCount() == 3
    assert tree.topLevelItemCount() == 1
    root_item = tree.topLevelItem(0)

    panel.folder_browser._open_item(root_item)

    assert root_item.isExpanded()
    assert root_item.childCount() == 1
    child_item = root_item.child(0)
    assert child_item.text(0) == "child"
    assert child_item.text(2) == "文件夹"
    assert not hasattr(panel.folder_browser, "_columns")

    selected = []
    panel.folders_selected.connect(selected.append)
    tree.clearSelection()
    tree.setCurrentItem(child_item)
    child_item.setSelected(True)
    panel.folder_browser._selection_changed()

    assert selected[-1] == [str(child)]
    assert panel.folder_browser.current_folder == str(child)


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


def test_header_uses_compact_plus_button_and_mode_switch():
    ensure_app()
    panel = keep_widget(LibraryPanel())

    assert panel.btn_add.text() == "＋"
    assert panel.btn_add.objectName() == "addMaterialFolderButton"
    assert panel.btn_add.size().width() == 36
    assert not hasattr(panel, "select_all_check")
    assert panel.mode_switch.minimumHeight() == 40


def test_folder_tree_supports_ctrl_style_multi_selection(tmp_path):
    ensure_app()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    panel = keep_widget(LibraryPanel())
    panel.set_directories([str(first), str(second)], [])
    emitted = []
    panel.folders_selected.connect(emitted.append)
    tree = panel.folder_browser.tree
    first_item = tree.topLevelItem(0)
    second_item = tree.topLevelItem(1)
    tree.clearSelection()
    first_item.setSelected(True)
    second_item.setSelected(True)
    tree.setCurrentItem(second_item)
    second_item.setSelected(True)
    first_item.setSelected(True)
    panel.folder_browser._selection_changed()

    assert emitted[-1] == [str(first), str(second)]


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
    panel.folders_selected.connect(selected.append)
    panel.set_directories([str(root)], [])

    panel._remove_directory(str(root))

    assert source.is_file()
    assert changes == [("music", [])]
    assert selected[-1] == []


def test_single_folder_tree_fills_available_width(tmp_path):
    app = ensure_app()
    root = tmp_path / "root"
    root.mkdir()
    (root / "song.mp3").write_bytes(b"")
    panel = keep_widget(LibraryPanel())
    panel.resize(900, 600)
    panel.set_directories([str(root)], [])
    panel.show()
    app.processEvents()

    assert panel.folder_browser.tree.width() > 700
