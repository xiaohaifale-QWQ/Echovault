import pytest

from server.http_server import resolve_library_path


def test_resolve_library_path_accepts_nested_file(tmp_path):
    root = tmp_path / "music"
    nested = root / "album" / "song.flac"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"audio")

    resolved = resolve_library_path(root, "album/song.flac")

    assert resolved == nested.resolve()


def test_resolve_library_path_rejects_parent_traversal(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="outside"):
        resolve_library_path(root, "../secret.txt")


def test_resolve_library_path_rejects_same_prefix_sibling(tmp_path):
    root = tmp_path / "music"
    sibling = tmp_path / "music_backup"
    root.mkdir()
    sibling.mkdir()

    with pytest.raises(ValueError, match="outside"):
        resolve_library_path(root, "../music_backup/secret.txt")
