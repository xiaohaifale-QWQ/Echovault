from pathlib import Path

from core.config import AppConfig
from tests.qt_test_app import ensure_app, keep_widget
from ui.transcribe_worker import TranscribeWorker
from ui.video_review_panel import VideoReviewPanel, shift_lrc_timestamps


def test_shift_lrc_timestamps_preserves_text_and_clamps_to_zero():
    content = "[00:01.00]first\n[00:03.50]second\n"

    assert shift_lrc_timestamps(content, 1.25) == (
        "[00:02.25]first\n[00:04.75]second\n"
    )
    assert shift_lrc_timestamps(content, -2.0).startswith("[00:00.00]first")


def test_video_review_lists_both_outputs_and_saves_subtitle_offset(tmp_path):
    ensure_app()
    video = tmp_path / "clip.mp4"
    audio = tmp_path / "clip.wav"
    subtitle = tmp_path / "clip.lrc"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    subtitle.write_text("[00:01.00]first\n[00:04.00]second\n", encoding="utf-8")
    panel = keep_widget(VideoReviewPanel())

    panel.set_results(str(video), str(audio), str(subtitle))
    panel.offset_spin.setValue(0.5)
    panel._position_changed(4700)

    assert panel.audio_result.text() == str(audio)
    assert panel.subtitle_result.text() == str(subtitle)
    assert panel.subtitle_list.count() == 2
    assert panel.subtitle_list.currentRow() == 1

    panel._save_calibration()

    assert subtitle.read_text(encoding="utf-8").startswith("[00:01.50]first")
    assert subtitle.with_suffix(".lrc.bak").is_file()
    assert panel.offset_spin.value() == 0.0


def test_video_transcription_persists_extracted_audio_and_text(
    monkeypatch,
    tmp_path,
):
    ensure_app()
    video = tmp_path / "meeting.mp4"
    video.write_bytes(b"video")
    converted = []

    def fake_extract(operation, inputs, output, params):
        assert operation == "extract"
        assert inputs == [str(video)]
        assert params["_preview"] is True
        source = inputs[0]
        converted.append((source, output))
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(b"wave")

    def fake_transcribe(*, audio_path, output_dir, **_kwargs):
        output = Path(output_dir) / f"{Path(audio_path).stem}.lrc"
        output.write_text("[00:01.00]text\n", encoding="utf-8")
        return str(output)

    monkeypatch.setattr("ui.transcribe_worker.process_audio", fake_extract)
    monkeypatch.setattr("ui.transcribe_worker.transcribe_and_save_lrc", fake_transcribe)
    worker = TranscribeWorker([str(video)], object(), AppConfig())
    completed = []
    worker.finished.connect(completed.append)

    worker.run()

    result = completed[0][str(video)]
    assert result["success"] is True
    assert Path(result["audio_path"]).is_file()
    assert Path(result["lrc_path"]).is_file()
    assert "Echovault视频处理" in result["audio_path"]
    assert converted[0][0] == str(video)
