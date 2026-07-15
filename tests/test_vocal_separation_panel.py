from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

from tests.qt_test_app import ensure_app, keep_widget
from ui.vocal_separation_panel import VocalSeparationPanel, WaveformView


def test_vocal_separation_panel_has_settings_above_mixer(tmp_path):
    ensure_app()
    panel = keep_widget(VocalSeparationPanel())
    song = tmp_path / "song.mp3"
    panel.set_songs([{"name": song.name, "path": str(song)}])

    assert panel._selected_path == str(song)
    assert panel.output_input.text() == str(tmp_path / "Separated")
    assert panel.selected_song_label.text() == song.name
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
    assert not hasattr(panel, "model_combo")
    assert not hasattr(panel, "device_combo")
    assert panel.pause_button.text() == "暂停"
    assert panel.speed_button.text() == "倍速 1x"
    assert panel.reverse_button.text() == "倒放"


def test_waveform_red_playhead_can_be_dragged():
    ensure_app()
    waveform = keep_widget(WaveformView("#123456"))
    waveform.resize(400, 80)
    waveform.show()
    ratios = []
    waveform.seek_requested.connect(ratios.append)

    QTest.mouseClick(waveform, Qt.MouseButton.LeftButton, pos=QPoint(300, 40))

    assert ratios
    assert 0.7 < ratios[-1] < 0.8
    assert waveform.playhead == ratios[-1]


def test_speed_button_cycles_from_one_to_ten_and_back():
    ensure_app()
    panel = keep_widget(VocalSeparationPanel())

    for _ in range(9):
        panel._cycle_playback_speed()
    assert panel._playback_speed == 10
    assert panel.speed_button.text() == "倍速 10x"

    panel._cycle_playback_speed()
    assert panel._playback_speed == 1
    assert panel.speed_button.text() == "倍速 1x"


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
