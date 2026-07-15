from ui import system_audio


def test_system_audio_binds_every_output_to_current_default(monkeypatch):
    class FakeDevices:
        @staticmethod
        def defaultAudioOutput():
            return FakeDevice()

    class FakeDevice:
        def isNull(self):
            return False

    class FakeOutput:
        def __init__(self):
            self.device = None
            self.muted = True

        def setDevice(self, selected):
            self.device = selected

        def setMuted(self, muted):
            self.muted = muted

    monkeypatch.setattr(system_audio, "QMediaDevices", FakeDevices)
    first = FakeOutput()
    second = FakeOutput()

    assert system_audio.apply_system_default_audio(first, second)
    assert isinstance(first.device, FakeDevice)
    assert isinstance(second.device, FakeDevice)
    assert first.muted is False
    assert second.muted is False


def test_system_audio_reports_missing_default(monkeypatch):
    class MissingDevice:
        def isNull(self):
            return True

    class FakeDevices:
        @staticmethod
        def defaultAudioOutput():
            return MissingDevice()

    monkeypatch.setattr(system_audio, "QMediaDevices", FakeDevices)

    assert not system_audio.apply_system_default_audio()
