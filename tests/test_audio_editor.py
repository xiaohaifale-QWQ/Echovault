import math
import struct
import wave
from pathlib import Path

import pytest

from core.audio_editor import _atempo_chain, process_audio
from core.audio_utils import find_ffmpeg, find_ffprobe, get_audio_info
from core.audio_waveform import extract_waveform_peaks
from core.metadata import read_tags, write_tags
from tests.qt_test_app import ensure_app, keep_widget
from ui.audio_editor_panel import (
    _WAVEFORM_CACHE,
    TOOLS,
    AudioEditorPanel,
    WaveformLoadWorker,
)
from ui.audio_timeline import AudioTimeline


def _write_sine_wave(path: Path, duration: float = 1.2) -> None:
    sample_rate = 16000
    frame_count = int(sample_rate * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        output.writeframes(frames)


def test_atempo_chain_keeps_each_ffmpeg_stage_in_supported_range():
    stages = _atempo_chain(4.0).split(",")

    assert stages == ["atempo=2.000000", "atempo=2.000000"]
    assert _atempo_chain(0.25).split(",") == [
        "atempo=0.500000",
        "atempo=0.500000",
    ]


@pytest.mark.skipif(
    not find_ffmpeg() or not find_ffprobe(),
    reason="FFmpeg integration is unavailable",
)
def test_audio_editor_trims_and_splits_real_wave(monkeypatch, tmp_path):
    source = tmp_path / "source.wav"
    _write_sine_wave(source)
    registered = []
    monkeypatch.setattr(
        "core.audio_editor.register_artifact",
        lambda *args: registered.append(args),
    )

    trimmed = tmp_path / "trimmed.wav"
    result = process_audio(
        "trim",
        [str(source)],
        str(trimmed),
        {"start": 0.2, "end": 0.8},
    )

    assert result.outputs == [str(trimmed)]
    assert 0.5 <= get_audio_info(str(trimmed))["duration"] <= 0.7

    split_base = tmp_path / "part.wav"
    split_result = process_audio(
        "split",
        [str(source)],
        str(split_base),
        {"segment_seconds": 0.4},
    )

    assert len(split_result.outputs) >= 3
    assert all(Path(path).is_file() for path in split_result.outputs)
    assert len(registered) == 1 + len(split_result.outputs)


def test_wav_common_tags_round_trip(tmp_path):
    source = tmp_path / "tagged.wav"
    _write_sine_wave(source, duration=0.1)

    write_tags(
        str(source),
        {
            "title": "测试标题",
            "artist": "测试歌手",
            "album": "测试专辑",
            "year": "2026",
            "track": "3",
        },
    )
    tags = read_tags(str(source))

    assert tags["title"] == "测试标题"
    assert tags["artist"] == "测试歌手"
    assert tags["album"] == "测试专辑"
    assert tags["year"] == "2026"
    assert tags["track"] == "3"


def test_audio_editor_rejects_overwriting_the_input(tmp_path):
    source = tmp_path / "source.wav"
    _write_sine_wave(source, duration=0.1)

    with pytest.raises(ValueError, match="不能覆盖"):
        process_audio("volume", [str(source)], str(source), {"gain_db": 1})


@pytest.mark.skipif(
    not find_ffmpeg() or not find_ffprobe(),
    reason="FFmpeg integration is unavailable",
)
def test_audio_editor_effects_and_waveform_follow_the_selected_range(tmp_path):
    source = tmp_path / "source.wav"
    _write_sine_wave(source, duration=1.2)

    peaks = extract_waveform_peaks(source, point_count=120)
    assert 50 <= len(peaks) <= 120
    assert any(low < 0 < high for low, high in peaks)

    selected = tmp_path / "selected.wav"
    process_audio(
        "volume",
        [str(source)],
        str(selected),
        {"gain_db": -3, "selection_start": 0.2, "selection_end": 0.7},
    )
    assert 0.45 <= get_audio_info(str(selected))["duration"] <= 0.55

    deleted = tmp_path / "deleted.wav"
    process_audio(
        "edit",
        [str(source)],
        str(deleted),
        {
            "selection_start": 0.2,
            "selection_end": 0.7,
            "crop_mode": "delete",
            "fade_in": 0.02,
            "gain_db": -1,
        },
    )
    assert 0.65 <= get_audio_info(str(deleted))["duration"] <= 0.75

    equalized = tmp_path / "equalized.wav"
    process_audio(
        "equalizer",
        [str(source)],
        str(equalized),
        {"bands": [2, 1, 0, -1, -2, 0, 1, 2], "balance": 10},
    )
    assert equalized.is_file()

    denoised = tmp_path / "denoised.wav"
    process_audio(
        "denoise",
        [str(source)],
        str(denoised),
        {"denoise_mode": 1, "strength": 18, "output_gain": 1.5},
    )
    assert denoised.is_file()

    stereo = tmp_path / "stereo.wav"
    process_audio(
        "mix",
        [str(source), str(source)],
        str(stereo),
        {
            "mix_mode": "stereo",
            "volumes": [0.8, 0.6],
            "master_gain": -1,
            "duration_mode": "longest",
        },
    )
    assert get_audio_info(str(stereo))["channels"] == 2


def test_audio_timeline_tracks_precise_selection_and_zoom():
    ensure_app()
    timeline = keep_widget(AudioTimeline())
    timeline.set_audio([(-0.5, 0.5)] * 100, 10.0)

    timeline.set_selection_seconds(2.0, 5.0)
    timeline.zoom_to_selection()

    assert timeline.has_selection()
    assert timeline.selection_start == 2.0
    assert timeline.selection_end == 5.0
    assert 0.0 < timeline.view_start < 0.2
    assert 0.5 < timeline.view_end < 1.0


def test_audio_timeline_reuses_static_waveform_while_playhead_moves():
    app = ensure_app()
    timeline = keep_widget(AudioTimeline())
    timeline.resize(800, 280)
    timeline.set_audio([(-0.5, 0.5)] * 4000, 120.0)
    timeline.show()
    app.processEvents()
    timeline.grab()
    initial_key = timeline._static_layer.cacheKey()

    timeline.set_playhead_seconds(20.0)
    timeline.set_selection_seconds(10.0, 30.0)
    app.processEvents()
    timeline.grab()

    assert timeline._static_layer.cacheKey() == initial_key
    timeline.zoom(0.5)
    app.processEvents()
    timeline.grab()
    assert timeline._static_layer.cacheKey() != initial_key


def test_waveform_worker_reuses_file_signature_cache(monkeypatch, tmp_path):
    ensure_app()
    _WAVEFORM_CACHE.clear()
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    calls = []
    monkeypatch.setattr(
        "ui.audio_editor_panel.get_audio_info",
        lambda _path: {"duration": 12.5},
    )
    monkeypatch.setattr(
        "ui.audio_editor_panel.extract_waveform_peaks",
        lambda _path: calls.append(_path) or [(-0.5, 0.5)],
    )
    results = []
    first = WaveformLoadWorker(str(source))
    first.completed.connect(lambda *args: results.append(args))
    first.run()
    second = WaveformLoadWorker(str(source))
    second.completed.connect(lambda *args: results.append(args))
    second.run()

    assert calls == [str(source)]
    assert results[0][2:] == (12.5, False)
    assert results[1][2:] == (12.5, True)


def test_audio_editor_only_updates_the_visible_workspace(monkeypatch, tmp_path):
    ensure_app()
    panel = keep_widget(AudioEditorPanel())
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    monkeypatch.setattr(panel, "_start_waveform_load", lambda _path: None)
    panel.show_song({"name": source.name, "path": str(source)})
    trim_page = panel.tool_pages["trim"]
    volume_page = panel.tool_pages["volume"]

    panel._waveform_loaded(str(source), [(-0.4, 0.4)] * 50, 10.0, False)

    assert trim_page.timeline.peaks
    assert volume_page.inputs() == []
    assert not volume_page.timeline.peaks
    panel._open_tool("volume")
    assert volume_page.inputs() == [str(source)]
    assert volume_page.timeline.peaks
    trim_page.timeline.playhead_seconds = 0.0
    panel._playing_path = str(source)
    panel._preview_position_changed(5000)
    assert volume_page.timeline.playhead_seconds == 5.0
    assert trim_page.timeline.playhead_seconds == 0.0


def test_audio_editor_panel_exposes_detailed_pages_for_every_processing_tool(
    tmp_path,
):
    ensure_app()
    panel = keep_widget(AudioEditorPanel())
    source = tmp_path / "song.wav"
    _write_sine_wave(source, duration=0.1)

    panel.show_song({"name": source.name, "path": str(source)})

    assert len(TOOLS) == 11
    assert set(panel.tool_pages) == {spec.key for spec in TOOLS}
    assert {"files", "record", "more", "edit", "fade"}.isdisjoint(panel.tool_pages)
    trim_page = panel.tool_pages["trim"]
    denoise_page = panel.tool_pages["denoise"]
    equalizer_page = panel.tool_pages["equalizer"]
    mix_page = panel.tool_pages["mix"]
    assert set(trim_page.fields) == {
        "gain_db",
        "speed",
        "semitones",
        "delay",
        "fade_in",
        "fade_out",
    }
    assert len(denoise_page.timelines) == 2
    assert len(equalizer_page.eq_bands) == 8
    assert set(equalizer_page.fields) == {"balance"}
    assert mix_page.track_editor is not None
    assert equalizer_page.inputs() == []
    panel._open_tool("equalizer")
    assert equalizer_page.inputs() == [str(source)]
    assert "Echovault编辑输出" in equalizer_page.output_edit.text()

    panel._open_tool("trim")
    assert panel.stack.currentWidget() is trim_page
    assert panel._waveform_worker.wait(5000)
    ensure_app().processEvents()
    trim_page.timeline.set_selection_seconds(0.02, 0.08)
    panel._open_tool("equalizer")
    assert equalizer_page.params()["selection_start"] == pytest.approx(0.02)
    assert equalizer_page.params()["selection_end"] == pytest.approx(0.08)
    assert equalizer_page.params()["bands"] == [0.0] * 8
