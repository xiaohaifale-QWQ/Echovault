from core.config import AppConfig
from tests.qt_test_app import ensure_app, keep_widget
from ui.main_window import MainWindow


def test_main_window_has_five_right_tabs_and_no_scattered_batch_buttons(monkeypatch):
    ensure_app()
    monkeypatch.setattr("ui.main_window.config_manager.load", AppConfig)
    monkeypatch.setattr(
        "ui.main_window.build_environment_report",
        lambda _config: {"ffmpeg": {"available": True}},
    )

    window = keep_widget(MainWindow())

    assert [
        window.right_tabs.tabText(index)
        for index in range(window.right_tabs.count())
    ] == ["详情", "素材库", "在线匹配", "批量处理", "同步"]
    assert not hasattr(window.song_list_panel, "btn_batch")
    assert not hasattr(window.detail_panel, "btn_batch_translate")

