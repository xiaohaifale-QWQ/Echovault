"""Application-wide coordination for audio preview players."""

from __future__ import annotations

from weakref import ReferenceType, WeakSet, ref

from PyQt6.QtMultimedia import QMediaPlayer


class PlaybackCoordinator:
    """Allow one logical playback session to own audio output at a time."""

    def __init__(self) -> None:
        self._sessions: WeakSet[PlaybackSession] = WeakSet()
        self._active_session: ReferenceType[PlaybackSession] | None = None

    def register(self, session: PlaybackSession) -> None:
        self._sessions.add(session)

    def claim(self, active_session: PlaybackSession) -> None:
        current = self._active_session() if self._active_session is not None else None
        if current is active_session:
            return
        if current is not None:
            current.pause()
        self._active_session = ref(active_session)


_GLOBAL_COORDINATOR = PlaybackCoordinator()


class PlaybackSession:
    """Group one or more synchronized players into a single playback session."""

    def __init__(
        self,
        *players: QMediaPlayer,
        coordinator: PlaybackCoordinator | None = None,
    ) -> None:
        if not players:
            raise ValueError("PlaybackSession requires at least one player")
        self._players = tuple(players)
        self._coordinator = coordinator or _GLOBAL_COORDINATOR
        self._coordinator.register(self)
        for player in self._players:
            player.playbackStateChanged.connect(self._on_state_changed)

    def play(self, player: QMediaPlayer) -> None:
        if player not in self._players:
            raise ValueError("Player is not part of this playback session")
        self._coordinator.claim(self)
        player.play()

    def play_all(self, players: tuple[QMediaPlayer, ...] | None = None) -> None:
        targets = self._players if players is None else players
        if any(player not in self._players for player in targets):
            raise ValueError("Player is not part of this playback session")
        self._coordinator.claim(self)
        for player in targets:
            player.play()

    def pause(self) -> None:
        for player in self._players:
            player.pause()

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._coordinator.claim(self)
