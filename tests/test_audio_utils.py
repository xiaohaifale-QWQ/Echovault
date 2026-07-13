import tempfile
from pathlib import Path

import pytest

from core.audio_utils import convert_to_whisper_format


def test_missing_ffmpeg_has_actionable_error_and_cleans_temp(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    temp_root = Path(tempfile.gettempdir())
    before = set(temp_root.glob("echovault_*.wav"))

    monkeypatch.setattr("core.audio_utils.find_ffmpeg", lambda: None)

    with pytest.raises(RuntimeError, match="未找到 ffmpeg"):
        convert_to_whisper_format(str(audio))

    assert set(temp_root.glob("echovault_*.wav")) == before
