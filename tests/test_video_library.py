from datetime import datetime

from core import video_library


def test_scan_videos_sorts_by_adjusted_capture_time_and_skips_outputs(tmp_path, monkeypatch):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mov"
    output = tmp_path / "视频汇总_20260714_120000" / "generated.mp4"
    for path in (first, second, output):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")

    timestamps = {
        first.resolve(): datetime(2026, 7, 14, 10, 0, 0),
        second.resolve(): datetime(2026, 7, 14, 9, 0, 0),
    }
    monkeypatch.setattr(video_library, "_probe_creation_time", lambda path: timestamps.get(path))

    videos = video_library.scan_videos(tmp_path, offset_seconds=60)

    assert [video["name"] for video in videos] == ["second.mov", "first.mp4"]
    assert videos[0]["captured_at"] == datetime(2026, 7, 14, 9, 1, 0)
    assert videos[0]["timestamp_source"] == "视频元数据"


def test_calibration_offset_maps_recorded_time_to_actual_time():
    assert video_library.calibration_offset_seconds(
        datetime(2020, 1, 1, 8, 0, 0),
        datetime(2026, 7, 14, 12, 0, 0),
    ) == 206164800
