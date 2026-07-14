import tempfile
import wave
from pathlib import Path

import pytest

from core.audio_utils import (
    cleanup_temp_files,
    convert_to_whisper_format,
    get_audio_info,
    split_audio,
)


def test_missing_ffmpeg_has_actionable_error_and_cleans_temp(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    temp_root = Path(tempfile.gettempdir())
    before = set(temp_root.glob("echovault_*.wav"))

    monkeypatch.setattr("core.audio_utils.find_ffmpeg", lambda: None)

    with pytest.raises(RuntimeError, match="未找到 ffmpeg"):
        convert_to_whisper_format(str(audio))

    assert set(temp_root.glob("echovault_*.wav")) == before


def test_audio_info_uses_bundled_ffprobe_compatible_output(tmp_path):
    audio = tmp_path / "song.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 16000)

    info = get_audio_info(str(audio))

    assert info["duration"] == pytest.approx(1.0)
    assert info["sample_rate"] == 16000
    assert info["channels"] == 1


def test_split_audio_uses_the_requested_short_chunk_duration(tmp_path):
    audio = tmp_path / "long.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 16_000 * 31)

    chunks = split_audio(str(audio), max_duration=15.0)
    try:
        assert len(chunks) == 3
        assert [get_audio_info(chunk)["duration"] for chunk in chunks] == pytest.approx(
            [15.0, 15.0, 1.0]
        )
    finally:
        cleanup_temp_files(chunks)
