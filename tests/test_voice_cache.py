import wave

from core.voice_cache import (
    cache_stats,
    clear_app_cache,
    clear_voice_cache,
    new_recording_path,
    pcm_to_wav,
    sent_transfer_cache_dir,
    voice_cache_dir,
)


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


def test_cache_stats_and_clear_include_sent_transfer_files(tmp_path):
    voice = voice_cache_dir(tmp_path) / "voice.wav"
    voice.write_bytes(b"1234")
    sent = sent_transfer_cache_dir(tmp_path) / "session" / "lyrics.lrc"
    sent.parent.mkdir(parents=True)
    sent.write_bytes(b"123456")

    stats = cache_stats(tmp_path)

    assert stats == {
        "voice_count": 1,
        "voice_size": 4,
        "sent_count": 1,
        "sent_size": 6,
        "total_count": 2,
        "total_size": 10,
    }
    removed = clear_app_cache(tmp_path)
    assert removed["total_count"] == 2
    assert cache_stats(tmp_path)["total_count"] == 0
