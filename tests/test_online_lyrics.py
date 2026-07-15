import json
from pathlib import Path

import pytest

from core.ai_assistant import AISettings
from core.online_lyrics import (
    LyricsMatch,
    apply_synced_lyrics,
    calibrate_lrc_with_reference,
    compare_lyrics,
    media_search_metadata,
    search_lrclib,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _match(**overrides):
    values = {
        "record_id": 1,
        "track_name": "Hello",
        "artist_name": "Artist",
        "album_name": "Album",
        "duration": 120.0,
        "instrumental": False,
        "plain_lyrics": "Hello\nWorld",
        "synced_lyrics": "[00:01.00]Hello\n[00:02.00]World",
    }
    values.update(overrides)
    return LyricsMatch(**values)


def test_lrclib_search_uses_user_agent_and_sorts_best_match_first():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return _Response(
            [
                {
                    "id": 2,
                    "trackName": "Different",
                    "artistName": "Other",
                    "albumName": "",
                    "duration": 300,
                    "instrumental": False,
                    "plainLyrics": "x",
                    "syncedLyrics": None,
                },
                {
                    "id": 1,
                    "trackName": "Hello",
                    "artistName": "Artist",
                    "albumName": "Album",
                    "duration": 121,
                    "instrumental": False,
                    "plainLyrics": "Hello",
                    "syncedLyrics": "[00:01.00]Hello",
                },
            ]
        )

    results = search_lrclib(
        "Hello", artist_name="Artist", duration=120, opener=opener
    )

    assert results[0].record_id == 1
    assert results[0].score > results[1].score
    assert "track_name=Hello" in captured["url"]
    assert captured["user_agent"].startswith("Echovault/")
    assert captured["timeout"] == 20.0


def test_media_metadata_falls_back_to_artist_title_filename(tmp_path):
    path = tmp_path / "Artist - Song.mp3"

    metadata = media_search_metadata(path)

    assert metadata.artist_name == "Artist"
    assert metadata.track_name == "Song"


def test_apply_synced_lyrics_creates_backup_and_replaces_only_lrc(tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio-unchanged")
    lrc = tmp_path / "song.lrc"
    lrc.write_text("[00:01.00]old", encoding="utf-8")

    output, backup = apply_synced_lyrics(lrc, _match())

    assert output == lrc
    assert backup == Path(str(lrc) + ".bak")
    assert backup.read_text(encoding="utf-8") == "[00:01.00]old"
    assert "[00:02.00]World" in lrc.read_text(encoding="utf-8")
    assert audio.read_bytes() == b"audio-unchanged"


def test_calibration_preserves_local_timestamps_and_backs_up(tmp_path):
    lrc = tmp_path / "song.lrc"
    original = "[00:01.230]Helo\n[00:04.50][00:08.50]Wold\n"
    lrc.write_text(original, encoding="utf-8")

    output, backup = calibrate_lrc_with_reference(
        lrc,
        "Hello\nWorld",
        ai_settings=AISettings(api_key="unused"),
        calibrator=lambda local, reference: ["Hello", "World"],
    )

    assert output == lrc
    assert backup.read_text(encoding="utf-8") == original
    assert lrc.read_text(encoding="utf-8") == (
        "[00:01.230]Hello\n[00:04.50][00:08.50]World\n"
    )


def test_calibration_does_not_write_or_backup_on_count_mismatch(tmp_path):
    lrc = tmp_path / "song.lrc"
    original = "[00:01.00]one\n[00:02.00]two\n"
    lrc.write_text(original, encoding="utf-8")

    with pytest.raises(RuntimeError, match="行数"):
        calibrate_lrc_with_reference(
            lrc,
            "one\ntwo",
            ai_settings=AISettings(api_key="unused"),
            calibrator=lambda local, reference: ["only one"],
        )

    assert lrc.read_text(encoding="utf-8") == original
    assert not Path(str(lrc) + ".bak").exists()


def test_calibration_validates_and_applies_ai_json(monkeypatch, tmp_path):
    lrc = tmp_path / "song.lrc"
    lrc.write_text("[00:01.00]Helo\n[00:02.00]Wold\n", encoding="utf-8")
    captured = {}

    def fake_complete(settings, messages, *, temperature):
        captured["settings"] = settings
        captured["messages"] = messages
        captured["temperature"] = temperature
        return '```json\n{"corrections":["Hello","World"]}\n```'

    monkeypatch.setattr("core.online_lyrics.complete", fake_complete)
    settings = AISettings(base_url="http://127.0.0.1:1234/v1", model="local")

    calibrate_lrc_with_reference(
        lrc,
        "Hello\nWorld",
        ai_settings=settings,
        track_name="Song",
        artist_name="Artist",
    )

    assert lrc.read_text(encoding="utf-8") == "[00:01.00]Hello\n[00:02.00]World\n"
    assert captured["settings"] == settings
    assert captured["temperature"] == 0.0
    assert "local_timeline_lines" in captured["messages"][1]["content"]


def test_compare_lyrics_reports_line_counts_and_similarity():
    comparison = compare_lyrics(
        "[00:01.00]Hello\n[00:02.00]World", "[00:08.00]Hello\n[00:09.00]World"
    )

    assert comparison["similarity"] == 1.0
    assert comparison["local_lines"] == 2
    assert comparison["reference_lines"] == 2
