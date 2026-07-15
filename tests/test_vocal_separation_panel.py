from core.vocal_separation import SEPARATION_MODELS
from tests.qt_test_app import ensure_app, keep_widget
from ui.vocal_separation_panel import VocalSeparationPanel


def test_vocal_separation_panel_has_settings_above_mixer(tmp_path):
    ensure_app()
    panel = keep_widget(VocalSeparationPanel())
    song = tmp_path / "song.mp3"
    panel.set_songs([{"name": song.name, "path": str(song)}])

    assert panel.song_combo.currentData() == str(song)
    assert panel.output_input.text() == str(tmp_path / "Separated")
    assert panel.model_combo.count() == len(SEPARATION_MODELS)
    assert panel.accompaniment_waveform is not None
    assert panel.vocal_waveform is not None
    assert not panel.play_button.isEnabled()
    assert not panel.save_mix_button.isEnabled()
