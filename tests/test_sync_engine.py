import os

from core.sync_engine import DiffType, SyncEngine


def _set_mtime(path, timestamp=1_700_000_000):
    os.utime(path, (timestamp, timestamp))


def test_same_mtime_different_size_is_conflict(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    file_a = dir_a / "song.mp3"
    file_b = dir_b / "song.mp3"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"bbbb")
    _set_mtime(file_a)
    _set_mtime(file_b)

    diffs = SyncEngine().compare_directories(str(dir_a), str(dir_b))

    assert len(diffs) == 1
    assert diffs[0].diff_type is DiffType.CONFLICT


def test_strict_mode_detects_same_size_different_content(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    file_a = dir_a / "song.flac"
    file_b = dir_b / "song.flac"
    file_a.write_bytes(b"aaaa")
    file_b.write_bytes(b"bbbb")
    _set_mtime(file_a)
    _set_mtime(file_b)

    engine = SyncEngine()

    assert engine.compare_directories(str(dir_a), str(dir_b)) == []
    strict_diffs = engine.compare_directories(str(dir_a), str(dir_b), compare_content=True)
    assert len(strict_diffs) == 1
    assert strict_diffs[0].diff_type is DiffType.CONFLICT
