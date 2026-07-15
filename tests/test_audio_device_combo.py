from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices

from tests.qt_test_app import ensure_app, keep_widget
from ui.audio_device_combo import AudioDeviceCombo


def test_audio_device_combo_lists_outputs_and_unmutes_selected_device():
    ensure_app()
    combo = keep_widget(AudioDeviceCombo())
    output = QAudioOutput(combo)
    output.setMuted(True)

    if QMediaDevices.audioOutputs():
        assert combo.isEnabled()
        assert combo.currentText()
        assert combo.apply_to(output)
        assert not output.isMuted()
        assert output.device().description() == combo.current_device().description()
    else:
        assert not combo.isEnabled()
        assert not combo.apply_to(output)


def test_audio_device_combo_avoids_virtual_default_for_real_speaker(monkeypatch):
    class Device:
        def __init__(self, device_id, description):
            self._id = device_id
            self._description = description

        def id(self):
            return self._id

        def description(self):
            return self._description

    outputs = [
        Device(b"virtual", "ASL (NVIDIA High Definition Audio)"),
        Device(b"headset", "扬声器 (HyperX Wireless)"),
    ]
    monkeypatch.setattr(AudioDeviceCombo, "_device_id", lambda device: device.id())

    assert AudioDeviceCombo._preferred_index(outputs, b"", b"virtual") == 1
    assert AudioDeviceCombo._preferred_index(outputs, b"virtual", b"virtual") == 0
