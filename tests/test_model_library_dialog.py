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
    dialog = keep_widget(ModelLibraryDialog())

    categories = {
        dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())
    }
    assert categories == {"本地识别", "人声分离"}
    assert dialog.table.rowCount() == 4 + len(SEPARATION_MODELS)
