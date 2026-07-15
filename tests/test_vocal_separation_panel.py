from PyQt6.QtWidgets import QMessageBox

from core.vocal_separation import SEPARATION_MODELS
from tests.qt_test_app import ensure_app, keep_widget
from ui.vocal_separation_panel import VocalSeparationPanel


def test_vocal_separation_panel_has_settings_above_mixer(tmp_path):
    ensure_app()
    panel = keep_widget(VocalSeparationPanel())
    song = tmp_path / "song.mp3"
    panel.set_songs([{"name": song.name, "path": str(song)}])

    assert panel._selected_path == str(song)
    assert panel.output_input.text() == str(tmp_path / "Separated")
    assert panel.model_combo.count() == len(SEPARATION_MODELS)
    assert panel.accompaniment_waveform is not None
    assert panel.vocal_waveform is not None
    assert panel.audio_device_combo.count() >= 1
    assert not panel.play_button.isEnabled()
    assert not panel.save_mix_button.isEnabled()
    assert "保存调音结果" in panel.save_mix_button.text()
    assert panel.save_mix_button.minimumHeight() >= 42
    assert panel.output_type_combo.count() == 3
    assert not hasattr(panel, "song_combo")
    assert not hasattr(panel, "mode_combo")


def test_missing_separation_model_requests_top_level_library(monkeypatch, tmp_path):
    ensure_app()
    panel = keep_widget(VocalSeparationPanel())
    song = tmp_path / "song.wav"
    panel.set_songs([{"name": song.name, "path": str(song)}])
    requested = []
    panel.model_library_requested.connect(lambda: requested.append(True))
    monkeypatch.setattr("ui.vocal_separation_panel.separation_available", lambda: True)
    monkeypatch.setattr(
        "ui.vocal_separation_panel.separation_model_installed", lambda _model: False
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    panel._start_separation()

    assert requested == [True]
