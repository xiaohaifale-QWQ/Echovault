"""Reusable live selector for Qt multimedia output devices."""

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtMultimedia import QAudioDevice, QAudioOutput, QMediaDevices
from PyQt6.QtWidgets import QComboBox


class AudioDeviceCombo(QComboBox):
    """List current audio outputs and reselect them after hot-plug changes."""

    device_changed = pyqtSignal(object)
    _VIRTUAL_OUTPUT_MARKERS = ("asl", "steam streaming")
    _SPEAKER_MARKERS = ("扬声器", "耳机", "speaker", "headphone", "headset")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self.refresh_devices)
        self.currentIndexChanged.connect(self._emit_current_device)
        self._settings = QSettings("Echovault", "Echovault")
        self.setMinimumWidth(170)
        self.refresh_devices()

    @staticmethod
    def _device_id(device: QAudioDevice) -> bytes:
        return bytes(device.id())

    @classmethod
    def _preferred_index(
        cls,
        outputs: list[QAudioDevice],
        saved_id: bytes,
        default_id: bytes,
    ) -> int:
        saved_index = next(
            (
                index
                for index, device in enumerate(outputs)
                if saved_id and cls._device_id(device) == saved_id
            ),
            -1,
        )
        if saved_index >= 0:
            saved_description = outputs[saved_index].description().lower()
            if not any(
                marker in saved_description for marker in cls._VIRTUAL_OUTPUT_MARKERS
            ):
                return saved_index

        default_index = next(
            (
                index
                for index, device in enumerate(outputs)
                if default_id and cls._device_id(device) == default_id
            ),
            -1,
        )
        if default_index >= 0:
            description = outputs[default_index].description().lower()
            if not any(marker in description for marker in cls._VIRTUAL_OUTPUT_MARKERS):
                return default_index

        for index, device in enumerate(outputs):
            description = device.description().lower()
            is_speaker = any(marker in description for marker in cls._SPEAKER_MARKERS)
            is_virtual = any(
                marker in description for marker in cls._VIRTUAL_OUTPUT_MARKERS
            )
            if is_speaker and not is_virtual:
                return index
        if saved_index >= 0:
            return saved_index
        return default_index if default_index >= 0 else (0 if outputs else -1)

    def refresh_devices(self):
        default = QMediaDevices.defaultAudioOutput()
        outputs = QMediaDevices.audioOutputs()
        saved_hex = self._settings.value("multimedia/output_device_id", "", str)
        try:
            saved_id = bytes.fromhex(saved_hex)
        except ValueError:
            saved_id = b""
        default_id = self._device_id(default) if not default.isNull() else b""
        self.blockSignals(True)
        self.clear()
        for device in outputs:
            prefix = "默认 · " if device.isDefault() else ""
            self.addItem(f"{prefix}{device.description()}", device)
        selected = self._preferred_index(outputs, saved_id, default_id)
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
        device = self.current_device()
        if not device.isNull():
            self._settings.setValue(
                "multimedia/output_device_id", self._device_id(device).hex()
            )
        self.device_changed.emit(device)
