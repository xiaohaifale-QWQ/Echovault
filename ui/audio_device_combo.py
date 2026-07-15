"""Reusable live selector for Qt multimedia output devices."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtMultimedia import QAudioDevice, QAudioOutput, QMediaDevices
from PyQt6.QtWidgets import QComboBox


class AudioDeviceCombo(QComboBox):
    """List current audio outputs and reselect them after hot-plug changes."""

    device_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self.refresh_devices)
        self.currentIndexChanged.connect(self._emit_current_device)
        self.setMinimumWidth(170)
        self.refresh_devices()

    @staticmethod
    def _device_id(device: QAudioDevice) -> bytes:
        return bytes(device.id())

    def refresh_devices(self):
        current = self.current_device()
        current_id = self._device_id(current) if not current.isNull() else b""
        default = QMediaDevices.defaultAudioOutput()
        outputs = QMediaDevices.audioOutputs()
        self.blockSignals(True)
        self.clear()
        for device in outputs:
            prefix = "默认 · " if device.isDefault() else ""
            self.addItem(f"{prefix}{device.description()}", device)
        selected = -1
        for index in range(self.count()):
            device = self.itemData(index)
            if current_id and self._device_id(device) == current_id:
                selected = index
                break
            is_default = (
                not default.isNull()
                and self._device_id(device) == self._device_id(default)
            )
            if selected < 0 and is_default:
                selected = index
        self.setCurrentIndex(selected if selected >= 0 else (0 if outputs else -1))
        self.setEnabled(bool(outputs))
        if not outputs:
            self.addItem("未检测到音频输出设备", QAudioDevice())
            self.setEnabled(False)
        self.blockSignals(False)
        self._emit_current_device()

    def current_device(self) -> QAudioDevice:
        device = self.currentData()
        return device if isinstance(device, QAudioDevice) else QAudioDevice()

    def apply_to(self, *outputs: QAudioOutput) -> bool:
        device = self.current_device()
        if device.isNull():
            return False
        for output in outputs:
            output.setDevice(device)
            output.setMuted(False)
        return True

    def _emit_current_device(self, _index: int = -1):
        self.device_changed.emit(self.current_device())
