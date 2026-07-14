import wave

from core.voice_cache import clear_voice_cache, new_recording_path, pcm_to_wav, voice_cache_dir


def test_voice_recording_cache_writes_wav_and_can_be_cleared(tmp_path):
    raw_path = tmp_path / "capture.pcm"
    raw_path.write_bytes(b"\0\0" * 160)
    recording_path = new_recording_path(tmp_path)

    pcm_to_wav(raw_path, recording_path)

    with wave.open(str(recording_path), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getnframes() == 160
    assert voice_cache_dir(tmp_path) == recording_path.parent
    assert clear_voice_cache(tmp_path) == 1
    assert not recording_path.exists()
