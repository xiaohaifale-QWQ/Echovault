from pathlib import Path

from core.online_lyrics import LyricsMatch, MediaSearchMetadata
from tests.qt_test_app import ensure_app, keep_widget
from ui.online_lyrics_panel import OnlineLyricsPanel


def _match():
    return LyricsMatch(
        record_id=10,
        track_name="Selected Song",
        artist_name="Singer",
        album_name="Album",
        duration=30.0,
        instrumental=False,
        plain_lyrics="online one\nonline two",
        synced_lyrics="[00:02.00]online one\n[00:15.00]online two",
        score=96.0,
    )


def test_online_panel_selects_songs_and_compares_two_editable_timelines(
    monkeypatch, tmp_path
):
    ensure_app()
    monkeypatch.setattr(
        "ui.online_lyrics_panel.media_search_metadata",
        lambda _path: MediaSearchMetadata("Selected Song", "Singer", "Album", 30.0),
    )
    media_path = tmp_path / "Selected Song.mp3"
    lrc_path = media_path.with_suffix(".lrc")
    lrc_path.write_text(
        "[00:01.00]local one\n[00:13.00]local two\n", encoding="utf-8"
    )
    panel = keep_widget(OnlineLyricsPanel())
    panel.set_songs(
        [
            {"name": "First.mp3", "path": str(tmp_path / "First.mp3")},
            {"name": media_path.name, "path": str(media_path)},
        ]
    )

    panel.song_selector.setCurrentIndex(1)
    panel._show_results([_match()])

    assert panel.song_selector.count() == 2
    assert panel.track_input.text() == "Selected Song"
    assert panel.candidate_selector.count() == 1
    assert "local two" in panel.local_editor.toPlainText()
    assert "online two" in panel.online_editor.toPlainText()
    assert panel.local_editor.highlight_at(13.0) == 1
    assert panel.online_editor.highlight_at(13.0) == 0

    panel._begin_editing(panel.local_editor)
    assert panel.local_editor.isReadOnly() is False


def test_online_panel_emits_explicit_cross_merge_choice(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr(
        "ui.online_lyrics_panel.media_search_metadata",
        lambda _path: MediaSearchMetadata("Song", "Artist", "", 10.0),
    )
    media_path = tmp_path / "Song.mp3"
    Path(media_path.with_suffix(".lrc")).write_text(
        "[00:01.00]local\n", encoding="utf-8"
    )
    panel = keep_widget(OnlineLyricsPanel())
    panel.show_song({"name": media_path.name, "path": str(media_path)})
    panel._show_results([_match()])
    captured = []
    panel.action_requested.connect(
        lambda path, payload, action: captured.append((path, payload, action))
    )

    panel._request_action("merge_local_timeline")

    assert captured[0][0] == str(media_path)
    assert captured[0][2] == "merge_local_timeline"
    assert "[00:01.00]local" in captured[0][1].local_content
    assert "[00:15.00]online two" in captured[0][1].online_content

