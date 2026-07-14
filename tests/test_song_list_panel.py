from pathlib import Path

from ui.song_list_panel import SongListPanel


def test_rename_updates_the_matching_song_not_the_first_record(tmp_path):
    old_path = tmp_path / "old.mp3"
    new_path = tmp_path / "renamed.mp3"
    new_lrc = tmp_path / "renamed.lrc"
    new_lrc.write_text("[00:00.00]歌词", encoding="utf-8")
    panel = SongListPanel.__new__(SongListPanel)
    panel._songs = [
        {"path": str(tmp_path / "first.mp3"), "name": "first.mp3", "has_lrc": False},
        {"path": str(old_path), "name": "old.mp3", "has_lrc": False},
    ]
    panel._instrumental = set()
    panel._mode = "music"
    panel._save_instrumental = lambda: None

    panel._update_renamed_song(str(old_path), str(new_path), new_path.name, new_lrc)

    assert panel._songs[0]["name"] == "first.mp3"
    assert panel._songs[1]["path"] == str(new_path)
    assert panel._songs[1]["name"] == "renamed.mp3"
    assert panel._songs[1]["lrc_path"] == str(new_lrc)
