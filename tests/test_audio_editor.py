import math
import struct
import wave
from pathlib import Path

import pytest

from core.audio_editor import _atempo_chain, process_audio
from core.audio_utils import find_ffmpeg, find_ffprobe, get_audio_info
from core.metadata import read_tags, write_tags
from tests.qt_test_app import ensure_app, keep_widget
from ui.audio_editor_panel import TOOLS, AudioEditorPanel


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


def test_audio_editor_panel_exposes_detailed_pages_for_every_processing_tool(
    tmp_path,
):
    ensure_app()
    panel = keep_widget(AudioEditorPanel())
    source = tmp_path / "song.wav"
    _write_sine_wave(source, duration=0.1)

    panel.show_song({"name": source.name, "path": str(source)})

    assert len(TOOLS) == 16
    assert set(panel.tool_pages) == {
        spec.key for spec in TOOLS if spec.operation not in {"files", "record"}
    }
    equalizer_page = panel.tool_pages["equalizer"]
    assert set(equalizer_page.fields) == {"bass", "middle", "treble"}
    assert equalizer_page.inputs() == [str(source)]
    assert "Echovault编辑输出" in equalizer_page.output_edit.text()

    panel._open_tool("equalizer")
    assert panel.stack.currentWidget() is equalizer_page
