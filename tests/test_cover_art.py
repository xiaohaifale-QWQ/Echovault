import json
import wave
from email.message import Message

from mutagen.id3 import ID3

from core.cover_art import (
    download_cover_art,
    search_cover_art,
    search_cover_art_fast,
)
from core.metadata import read_cover_art, write_cover_art

JPEG = b"\xff\xd8\xff\xe0" + b"cover"
PNG = b"\x89PNG\r\n\x1a\n" + b"cover"


class _Response:
    def __init__(self, payload, content_type="application/json"):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


def test_cover_search_uses_musicbrainz_and_cover_art_archive():
    captured = []

    def opener(request, timeout):
        captured.append((request.full_url, request.get_header("User-agent"), timeout))
        if "musicbrainz.org" in request.full_url:
            return _Response(
                {
                    "release-groups": [
                        {
                            "id": "group-1",
                            "title": "Album",
                            "score": 98,
                            "first-release-date": "2020-01-02",
                            "artist-credit": [{"name": "Singer"}],
                        }
                    ]
                }
            )
        return _Response(
            {
                "images": [
                    {
                        "front": True,
                        "image": "https://img/full.jpg",
                        "thumbnails": {
                            "250": "https://img/250.jpg",
                            "500": "https://img/500.jpg",
                            "1200": "https://img/1200.jpg",
                        },
                    }
                ]
            }
        )

    matches = search_cover_art(
        "Song",
        artist_name="Singer",
        album_name="Album",
        opener=opener,
    )

    assert matches[0].release_group_id == "group-1"
    assert matches[0].image_url == "https://img/1200.jpg"
    assert matches[0].thumbnail_url == "https://img/500.jpg"
    assert "releasegroup%3A%22Album%22" in captured[0][0]
    assert captured[0][1].startswith("Echovault/")


def test_fast_cover_search_uses_single_round_trip_when_apple_has_artwork():
    captured = []

    def opener(request, timeout):
        captured.append(request.full_url)
        return _Response(
            {
                "resultCount": 1,
                "results": [
                    {
                        "collectionId": 10,
                        "trackName": "Song",
                        "artistName": "Singer",
                        "collectionName": "Album",
                        "releaseDate": "2024-01-01T00:00:00Z",
                        "artworkUrl100": "https://img/100x100bb.jpg",
                    }
                ],
            }
        )

    matches = search_cover_art_fast(
        "Song",
        artist_name="Singer",
        album_name="Album",
        opener=opener,
    )

    assert len(captured) == 1
    assert "itunes.apple.com/search" in captured[0]
    assert matches[0].image_url == "https://img/1200x1200bb.jpg"
    assert matches[0].thumbnail_url == "https://img/100x100bb.jpg"
    assert matches[0].source == "Apple iTunes Search"


def test_download_cover_validates_image_type():
    data, mime_type = download_cover_art(
        "https://img/cover.jpg",
        opener=lambda _request, timeout: _Response(JPEG, "image/jpeg"),
    )

    assert data == JPEG
    assert mime_type == "image/jpeg"


def test_mp3_cover_can_be_written_and_read(monkeypatch, tmp_path):
    class FakeAudio:
        def __init__(self):
            self.tags = ID3()
            self.saved = False

        def add_tags(self):
            self.tags = ID3()

        def save(self):
            self.saved = True

    audio = FakeAudio()
    registered = []
    monkeypatch.setattr("core.metadata._get_mutagen_file", lambda _path: audio)
    monkeypatch.setattr(
        "core.transfer_session.register_artifact",
        lambda *args: registered.append(args),
    )
    path = tmp_path / "song.mp3"

    write_cover_art(str(path), JPEG, "image/jpeg")
    cover = read_cover_art(str(path))

    assert audio.saved
    assert cover == (JPEG, "image/jpeg")
    assert registered[0][2] == "cover_art"


def test_flac_cover_replaces_old_picture(monkeypatch, tmp_path):
    class FakeFlac:
        def __init__(self):
            self.pictures = []

        def clear_pictures(self):
            self.pictures.clear()

        def add_picture(self, picture):
            self.pictures.append(picture)

        def save(self):
            pass

    audio = FakeFlac()
    monkeypatch.setattr("core.metadata._get_mutagen_file", lambda _path: audio)
    monkeypatch.setattr(
        "core.transfer_session.register_artifact",
        lambda *_args: True,
    )
    path = tmp_path / "song.flac"

    write_cover_art(str(path), PNG, "image/png")

    assert read_cover_art(str(path)) == (PNG, "image/png")


def test_wav_cover_roundtrip_uses_real_mutagen_file(monkeypatch, tmp_path):
    path = tmp_path / "song.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 80)
    monkeypatch.setattr(
        "core.transfer_session.register_artifact",
        lambda *_args: True,
    )

    write_cover_art(str(path), JPEG, "image/jpeg")

    assert read_cover_art(str(path)) == (JPEG, "image/jpeg")
