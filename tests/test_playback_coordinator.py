from PyQt6.QtMultimedia import QMediaPlayer

from ui.playback_coordinator import PlaybackCoordinator, PlaybackSession


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, value):
        for callback in tuple(self.callbacks):
            callback(value)


class FakePlayer:
    def __init__(self):
        self.playbackStateChanged = FakeSignal()
        self.play_calls = 0
        self.pause_calls = 0

    def play(self):
        self.play_calls += 1
        self.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)

    def pause(self):
        self.pause_calls += 1
        self.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PausedState)


def test_playback_coordinator_keeps_only_one_logical_session_active():
    coordinator = PlaybackCoordinator()
    accompaniment = FakePlayer()
    vocals = FakePlayer()
    editor = FakePlayer()
    separation_session = PlaybackSession(
        accompaniment, vocals, coordinator=coordinator
    )
    editor_session = PlaybackSession(editor, coordinator=coordinator)

    separation_session.play_all()

    assert accompaniment.play_calls == 1
    assert vocals.play_calls == 1
    assert accompaniment.pause_calls == 0
    assert vocals.pause_calls == 0

    editor_session.play(editor)

    assert editor.play_calls == 1
    assert accompaniment.pause_calls == 1
    assert vocals.pause_calls == 1

    accompaniment.play()

    assert editor.pause_calls == 1
