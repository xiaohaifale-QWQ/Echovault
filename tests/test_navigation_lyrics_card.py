from tests.qt_test_app import ensure_app, keep_widget
from ui.navigation_lyrics_card import NavigationLyricsCard


def test_navigation_lyrics_card_shows_song_and_tracks_active_line(tmp_path):
    ensure_app()
    media_path = tmp_path / "A Very Long Song.mp3"
    lrc_path = media_path.with_suffix(".lrc")
    lrc_path.write_text(
        "[00:01.00]第一句\n[00:04.50]第二句\n[00:08.00]第三句\n",
        encoding="utf-8",
    )
    card = keep_widget(NavigationLyricsCard())

    card.set_song(
        {
            "name": media_path.name,
            "path": str(media_path),
            "lrc_path": str(lrc_path),
            "has_lrc": True,
        }
    )

    assert card.song_label.text() == "A Very Long Song"
    assert card.lyrics_list.count() == 3
    assert card.current_lyric_index == -1

    card.set_position_ms(5200)

    assert card.current_lyric_index == 1
    assert card.lyrics_list.currentItem().text() == "第二句"
    assert card.time_label.text() == "00:05"


def test_navigation_lyrics_card_reloads_matching_lrc_only(tmp_path):
    ensure_app()
    media_path = tmp_path / "song.flac"
    lrc_path = media_path.with_suffix(".lrc")
    lrc_path.write_text("[00:00.00]旧歌词\n", encoding="utf-8")
    card = keep_widget(NavigationLyricsCard())
    card.set_song({"path": str(media_path), "lrc_path": str(lrc_path)})

    lrc_path.write_text("[00:00.00]新歌词\n", encoding="utf-8")
    card.reload_lyrics(str(lrc_path))

    assert card.lyrics_list.item(0).text() == "新歌词"
