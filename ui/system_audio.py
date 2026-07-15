"""Keep media players bound to the current Windows system output."""

from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices


def apply_system_default_audio(*outputs: QAudioOutput) -> bool:
    """Bind every output to the current system default and ensure it is audible."""

    device = QMediaDevices.defaultAudioOutput()
    if device.isNull():
        return False
    for output in outputs:
        output.setDevice(device)
        output.setMuted(False)
    return True
