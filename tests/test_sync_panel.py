from core.artifact_diff import ArtifactDiff
from core.config import AppConfig
from core.transfer_session import TransferSessionManager
from tests.qt_test_app import ensure_app, keep_widget
from ui.sync_panel import SyncPanel


def test_sync_panel_exposes_separate_send_receive_and_advanced_pages(
    monkeypatch, tmp_path
):
    ensure_app()
    config = AppConfig()
    monkeypatch.setattr("ui.sync_panel.config_manager.load", lambda: config)
    monkeypatch.setattr("ui.sync_panel.config_manager.save", lambda: None)

    panel = keep_widget(
        SyncPanel(
            session_manager=TransferSessionManager(
                tmp_path / "state",
                outbox_dir=tmp_path / "outbox",
                sent_cache_dir=tmp_path / "cache",
            )
        )
    )

    assert panel.receiver_button.text() == "开启接收"
    assert panel.open_receive_button.text() == "打开"
    assert panel.browse_receive_button.text() == "选择"
    assert panel.send_button.text() == "发送 0 个文件"
    assert panel.add_send_files_button.text() == "添加文件"
    assert panel.add_send_folder_button.text() == "添加文件夹"
    assert panel.receive_queue.columnCount() == 4
    assert panel.send_page.objectName() == "phoneSendPage"
    assert panel.receive_page.objectName() == "phoneReceivePage"
    assert panel.advanced_sync_page.objectName() == "advancedFolderSyncPage"
    assert "QWidget#phoneSendPage" in panel.styleSheet()
    assert "background: #FFFFFF" in panel.send_page.styleSheet()
    assert panel.send_page.styleSheet() == panel.receive_page.styleSheet()
    assert panel.send_page.styleSheet() == panel.advanced_sync_page.styleSheet()
    assert panel.send_page.isAncestorOf(panel.send_button)
    assert panel.receive_page.isAncestorOf(panel.receiver_button)
    assert panel.advanced_sync_page.isAncestorOf(panel.folder_sync_panel)
    assert not panel.advanced_group.isCheckable()
    assert not panel.folder_sync_panel.isHidden()

    panel.set_dir_a(str(tmp_path / "music"))
    assert panel.receive_dir_input.text().endswith("Echovault接收")
    assert panel.folder_sync_panel.dir_a_input.text().endswith("music")
    assert panel.outbox_path_label.text().endswith("待回传")
    assert panel.select_all_diffs_button.text() == "全选差异"
    assert panel.clear_selection_button.text() == "清除选择"
    assert panel.conflict_rule_combo.currentText() == "重名时自动重命名"
    assert not hasattr(panel, "filter_combo")

    panel._diffs = [
        ArtifactDiff("pending.lrc", "pending.lrc", "generated", 10),
        ArtifactDiff("original.mp3", "original.mp3", "unchanged", 10),
        ArtifactDiff(
            "sent.lrc",
            "sent.lrc",
            "generated",
            10,
            returned=True,
        ),
    ]
    assert [diff.relative_path for diff in panel._filtered_diffs()] == ["pending.lrc"]
