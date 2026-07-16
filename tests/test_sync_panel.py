from core.artifact_diff import ArtifactDiff
from core.config import AppConfig
from core.transfer_session import TransferSessionManager
from tests.qt_test_app import ensure_app, keep_widget
from ui.sync_panel import SyncPanel


def test_sync_panel_uses_phone_task_workflow_and_hides_advanced_sync(
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
    assert panel.send_button.text() == "发送选中的文件到手机"
    assert panel.advanced_group.isCheckable()
    assert panel.advanced_group.isChecked() is False
    assert panel.folder_sync_panel.isHidden()

    panel.set_dir_a(str(tmp_path / "music"))
    assert panel.receive_dir_input.text().endswith("Echovault接收")
    assert panel.folder_sync_panel.dir_a_input.text().endswith("music")
    assert panel.outbox_path_label.text().endswith("待回传")

    panel._diffs = [
        ArtifactDiff("pending.lrc", "pending.lrc", "generated", 10),
        ArtifactDiff(
            "sent.lrc",
            "sent.lrc",
            "generated",
            10,
            returned=True,
        ),
    ]
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData("generated"))
    assert [diff.relative_path for diff in panel._filtered_diffs()] == ["pending.lrc"]
