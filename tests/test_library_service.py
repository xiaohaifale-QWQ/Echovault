import json

import pytest

from services.library_service import InstrumentalStore, scan_audio


def test_scan_audio_supports_uppercase_extensions_and_markers(tmp_path):
    audio = tmp_path / "Artist - Song.MP3"
    audio.write_bytes(b"audio")
    audio.with_suffix(".lrc").write_text("[00:00.00]test", encoding="utf-8")
    InstrumentalStore(tmp_path).set_marked(audio, True)

    songs = scan_audio(tmp_path)

    assert len(songs) == 1
    assert songs[0]["name"] == audio.name
    assert songs[0]["has_lrc"] is True
    assert songs[0]["instrumental"] is True


def test_store_migrates_legacy_absolute_paths_to_relative_paths(tmp_path):
    audio = tmp_path / "legacy.flac"
    audio.write_bytes(b"audio")
    marker = tmp_path / ".musicsync_instrumental.json"
    marker.write_text(json.dumps({str(audio): True}), encoding="utf-8")

    store = InstrumentalStore(tmp_path)
    assert store.is_marked(audio)

    store.replace(store.absolute_paths())
    saved = json.loads(marker.read_text(encoding="utf-8"))
    assert saved == {"schema_version": 1, "instrumental": ["legacy.flac"]}


def test_store_rejects_paths_outside_library(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")

    store = InstrumentalStore(library)

    with pytest.raises(ValueError, match="不在音乐库"):
        store.set_marked(outside, True)
