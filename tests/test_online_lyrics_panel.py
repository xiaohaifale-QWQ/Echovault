import base64
from pathlib import Path

from core.online_lyrics import LyricsMatch, MediaSearchMetadata
from tests.qt_test_app import ensure_app, keep_widget
from ui.online_lyrics_panel import (
    CoverApplyAction,
    OnlineLyricsComparisonPane,
    OnlineLyricsPanel,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
    comparison = keep_widget(OnlineLyricsComparisonPane())
    panel.bind_comparison_pane(comparison)
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
    assert panel.results_table.rowCount() == 1
    assert "local two" in comparison.local_editor.toPlainText()
    assert "online two" in comparison.online_editor.toPlainText()
    assert comparison.local_editor.highlight_at(13.0) == 1
    assert comparison.online_editor.highlight_at(13.0) == 0
    assert not hasattr(comparison, "audio_device_combo")
    assert comparison.media_devices is not None

    comparison._begin_editing(comparison.local_editor)
    assert comparison.local_editor.isReadOnly() is False


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
    comparison = keep_widget(OnlineLyricsComparisonPane())
    panel.bind_comparison_pane(comparison)
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


def test_online_panel_offers_local_recognition_without_local_lrc(
    monkeypatch, tmp_path
):
    ensure_app()
    monkeypatch.setattr(
        "ui.online_lyrics_panel.media_search_metadata",
        lambda _path: MediaSearchMetadata("Song", "", "", 10.0),
    )
    media_path = tmp_path / "Song.mp3"
    panel = keep_widget(OnlineLyricsPanel())
    comparison = keep_widget(OnlineLyricsComparisonPane())
    panel.bind_comparison_pane(comparison)
    panel.show_song({"name": media_path.name, "path": str(media_path)})
    captured = []
    panel.action_requested.connect(
        lambda path, payload, action: captured.append((path, payload, action))
    )

    assert not panel.transcribe_button.isHidden()
    assert panel.transcribe_button.isEnabled()

    panel._request_action("transcribe_local")

    assert captured == [(str(media_path), None, "transcribe_local")]


def test_online_panel_simplifies_selected_candidate(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr(
        "ui.online_lyrics_panel.media_search_metadata",
        lambda _path: MediaSearchMetadata("Song", "", "", 10.0),
    )
    media_path = tmp_path / "Song.mp3"
    panel = keep_widget(OnlineLyricsPanel())
    comparison = keep_widget(OnlineLyricsComparisonPane())
    panel.bind_comparison_pane(comparison)
    panel.show_song({"name": media_path.name, "path": str(media_path)})
    match = _match()
    match = LyricsMatch(
        **{
            **match.__dict__,
            "synced_lyrics": "[00:01.00]繁體歌詞：愛與夢",
        }
    )

    panel._show_results([match])

    assert comparison.online_content() == "[00:01.00]繁体歌词：爱与梦"


def test_online_panel_separates_music_and_video_sources():
    ensure_app()
    panel = keep_widget(OnlineLyricsPanel())
    panel.set_songs(
        [
            {
                "name": "Audio.mp3",
                "path": "C:/media/Audio.mp3",
                "material_type": "music",
            },
            {
                "name": "Clip.mp4",
                "path": "C:/video/Clip.mp4",
                "material_type": "video",
            },
        ]
    )

    assert [panel.song_selector.itemText(index) for index in range(2)] == [
        "[音乐] Audio",
        "[视频] Clip",
    ]

    panel.source_filter.setCurrentIndex(panel.source_filter.findData("video"))

    assert panel.song_selector.count() == 1
    assert panel.song_selector.itemText(0) == "[视频] Clip"
    panel.song_selector.setCurrentIndex(0)
    assert not panel.apply_cover_button.isEnabled()
    assert not panel.local_cover_button.isEnabled()


def test_online_panel_supports_online_and_local_cover_actions(monkeypatch, tmp_path):
    ensure_app()
    monkeypatch.setattr(
        "ui.online_lyrics_panel.media_search_metadata",
        lambda _path: MediaSearchMetadata("Song", "Singer", "Album", 10.0),
    )
    monkeypatch.setattr("ui.online_lyrics_panel.read_cover_art", lambda _path: None)
    media_path = tmp_path / "Song.mp3"
    media_path.write_bytes(b"audio")
    panel = keep_widget(OnlineLyricsPanel())
    panel.show_song(
        {
            "name": media_path.name,
            "path": str(media_path),
            "material_type": "music",
        }
    )
    captured = []
    panel.action_requested.connect(
        lambda path, payload, action: captured.append((path, payload, action))
    )

    assert panel.search_cover_button.text() == "搜索在线封面"
    assert panel.local_cover_button.text() == "选择本地封面"
    assert panel.apply_cover_button.text() == "写入音频标签"

    assert panel._set_cover_preview(PNG, "image/png", "本地封面：cover.png")
    panel._request_cover_apply()

    assert captured[0][0] == str(media_path)
    assert captured[0][2] == "apply_cover"
    assert isinstance(captured[0][1], CoverApplyAction)
    assert captured[0][1].image_data == PNG
