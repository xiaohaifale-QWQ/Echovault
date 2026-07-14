from datetime import datetime

from core import video_aggregation


def test_aggregate_writes_manifest_and_uses_copy_before_reencoding(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    videos = [
        {
            "path": str(source),
            "captured_at": datetime(2026, 7, 14, 10, 0, 0),
            "timestamp_source": "视频元数据",
        }
    ]
    commands = []
    monkeypatch.setattr(video_aggregation, "scan_videos", lambda *_args, **_kwargs: videos)
    monkeypatch.setattr(video_aggregation, "find_ffmpeg", lambda: "ffmpeg.exe")
    def fake_run(command):
        commands.append(command)
        return True

    monkeypatch.setattr(video_aggregation, "_run_ffmpeg", fake_run)

    result = video_aggregation.aggregate_videos_by_time(tmp_path)

    assert result.video_count == 1
    assert not result.reencoded
    assert result.manifest_path.exists()
    assert "-c" in commands[0] and "copy" in commands[0]
