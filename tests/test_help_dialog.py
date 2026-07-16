from tests.qt_test_app import ensure_app, keep_widget
from ui.help_dialog import HELP_SECTIONS, HelpDialog


def test_help_dialog_exposes_local_ai_mcp_translation_separation_and_matching_guides():
    ensure_app()
    dialog = keep_widget(HelpDialog())

    assert dialog.tabs.count() == 7
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        section[0] for section in HELP_SECTIONS
    ]
    assert "11434/v1" in dialog.pages["本地部署 AI"].toPlainText()
    assert "confirmed=true" in dialog.pages["AI 接口与 MCP"].toPlainText()
    assert "Argos" in dialog.pages["歌词翻译"].toPlainText()
    assert "HTDemucs" in dialog.pages["人声分离"].toPlainText()
    assert "LRCLIB" in dialog.pages["在线歌词"].toPlainText()
    assert "发送回去" in dialog.pages["手机传输"].toPlainText()
