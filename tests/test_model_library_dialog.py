from core.audio_enhancement import ENHANCEMENT_MODELS
from core.config import AppConfig
from core.runtime_detection import HardwareReport
from core.vocal_separation import SEPARATION_MODELS
from tests.qt_test_app import ensure_app, keep_widget
from ui.model_library_dialog import ModelLibraryDialog


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

    assert dialog.asr_card.objectName() == "asrModelCard"
    assert dialog.separation_card.objectName() == "separationModelCard"
    assert dialog.asr_table.rowCount() == 4
    assert dialog.separation_table.rowCount() == len(SEPARATION_MODELS) + len(
        ENHANCEMENT_MODELS
    )
    assert dialog.separation_table.minimumHeight() >= 235
    assert dialog.separation_model_combo.count() == len(SEPARATION_MODELS)
    assert dialog.separation_model_combo.currentData() == "htdemucs"
    assert not dialog.separation_gpu_check.isEnabled()
    assert "CPU 运行时" in dialog.separation_runtime_label.text()
