from core.audio_enhancement import ENHANCEMENT_MODELS
from core.config import AppConfig, config_manager
from core.runtime_detection import HardwareReport
from core.vocal_separation import SEPARATION_MODELS
from tests.qt_test_app import ensure_app, keep_widget
from ui.model_library_dialog import ModelLibraryDialog
from ui.settings_dialog import SettingsDialog


def test_model_library_contains_asr_and_separation_models(monkeypatch):
    ensure_app()
    monkeypatch.setattr(
        ModelLibraryDialog,
        "_installed",
        staticmethod(lambda _model: False),
    )
    monkeypatch.setattr(
        "ui.model_library_dialog.detect_hardware",
        lambda: HardwareReport("win_amd64", 19045, ()),
    )
    monkeypatch.setattr(
        "ui.model_library_dialog.separation_gpu_available", lambda: False
    )
    dialog = keep_widget(ModelLibraryDialog(config=AppConfig()))

    assert dialog.online_card.objectName() == "onlineModelCard"
    assert dialog.asr_card.objectName() == "asrModelCard"
    assert dialog.separation_card.objectName() == "separationModelCard"
    assert dialog.online_table.rowCount() == 2
    assert dialog.asr_table.rowCount() == 4
    assert dialog.separation_table.rowCount() == len(SEPARATION_MODELS) + len(
        ENHANCEMENT_MODELS
    )
    assert dialog.separation_table.minimumHeight() >= 235
    assert dialog.asr_table.rowHeight(0) >= 44
    assert dialog.online_table.cellWidget(0, 4).objectName() == "modelActionButton"
    assert dialog.asr_table.cellWidget(0, 6).objectName() == "modelActionButton"
    assert dialog.separation_model_combo.count() == len(SEPARATION_MODELS)
    assert dialog.separation_model_combo.currentData() == "htdemucs"
    assert not dialog.separation_gpu_check.isEnabled()
    assert "CPU 运行时" in dialog.separation_runtime_label.text()


def test_model_library_selects_configured_online_model(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr(config_manager, "config_path", tmp_path / "config.json")
    monkeypatch.setattr(
        ModelLibraryDialog,
        "_installed",
        staticmethod(lambda _model: False),
    )
    monkeypatch.setattr(
        "ui.model_library_dialog.detect_hardware",
        lambda: HardwareReport("win_amd64", 19045, ()),
    )
    monkeypatch.setattr(
        "ui.model_library_dialog.separation_gpu_available", lambda: False
    )
    config = AppConfig()
    config.asr.provider = "local"
    config.xunfei_app_id = "app"
    config.xunfei_api_key = "key"
    config.xunfei_api_secret = "secret"
    dialog = keep_widget(ModelLibraryDialog(config=config))

    assert dialog.online_table.item(1, 3).text() == "已配置"
    dialog.online_table.cellWidget(1, 4).click()

    assert config.asr.provider == "xunfei"
    assert dialog.online_table.item(1, 3).text() == "正在使用 ✓"


def test_model_library_selects_installed_local_model(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr(config_manager, "config_path", tmp_path / "config.json")
    monkeypatch.setattr(
        ModelLibraryDialog,
        "_installed",
        staticmethod(lambda model: model.category == "asr" and model.key == "base"),
    )
    monkeypatch.setattr(
        "ui.model_library_dialog.detect_hardware",
        lambda: HardwareReport("win_amd64", 19045, ()),
    )
    monkeypatch.setattr(
        "ui.model_library_dialog.separation_gpu_available", lambda: False
    )
    config = AppConfig()
    config.asr.provider = "xunfei"
    config.asr.local_model = "tiny"
    dialog = keep_widget(ModelLibraryDialog(config=config))

    assert dialog.asr_table.cellWidget(1, 6).text() == "使用"
    dialog.asr_table.cellWidget(1, 6).click()

    assert config.asr.provider == "local"
    assert config.asr.local_model == "base"
    assert dialog.asr_table.item(1, 5).text() == "正在使用 ✓"


def test_recognition_settings_points_model_selection_to_library(monkeypatch):
    ensure_app()
    monkeypatch.setattr(SettingsDialog, "_on_scan_gpu", lambda _self: None)
    config = AppConfig()
    config.asr.provider = "xunfei"

    dialog = keep_widget(SettingsDialog(config, section="recognition"))

    assert dialog.active_asr_label.text() == "在线模型 · 讯飞云端识别"
    assert dialog.open_model_library_button.text() == "打开模型库选择模型"
    assert not hasattr(dialog, "provider_combo")
    assert not hasattr(dialog, "cloud_provider_combo")
