from pathlib import Path

from core.asr.base import Segment, TranscriptionResult
from core.lrc_parser import parse_lrc_file
from core.lrc_writer import transcribe_and_save_lrc
from core.vocal_separation import SeparationResult


class FakeRouter:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path, language=None):
        self.calls.append((audio_path, language))
        return TranscriptionResult(
            segments=[Segment(1.0, 2.0, f"line-{len(self.calls)}")],
            language="zh",
            duration=10.0,
        )


def test_pipeline_offsets_chunks_and_writes_complete_lrc(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    chunks = [tmp_path / "chunk-1.wav", tmp_path / "chunk-2.wav"]
    for chunk in chunks:
        chunk.write_bytes(b"wav")

    monkeypatch.setattr("core.audio_utils.split_audio", lambda *_args, **_kwargs: chunks)
    monkeypatch.setattr("core.audio_utils.cleanup_temp_files", lambda _paths: None)
    router = FakeRouter()

    lrc_path = transcribe_and_save_lrc(str(audio), router, language="zh")
    parsed = parse_lrc_file(lrc_path)

    assert len(router.calls) == 2
    assert [line.timestamp for line in parsed.lines] == [1.0, 601.0]
    assert not Path(lrc_path + ".tmp").exists()


def test_pipeline_recognizes_separated_vocals_when_enabled(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"vocals")
    accompaniment = tmp_path / "accompaniment.wav"
    accompaniment.write_bytes(b"music")
    observed = {}

    def fake_separate(input_path, output_dir, **kwargs):
        observed["input"] = input_path
        observed["output_dir"] = output_dir
        observed["device"] = kwargs["device"]
        kwargs["progress"](50, "正在分离…")
        return SeparationResult(vocals, accompaniment, 44100)

    monkeypatch.setattr("core.vocal_separation.separate_vocals", fake_separate)
    monkeypatch.setattr(
        "core.audio_utils.split_audio", lambda input_path, **_kwargs: [input_path]
    )
    monkeypatch.setattr("core.audio_utils.cleanup_temp_files", lambda _paths: None)
    router = FakeRouter()
    events = []

    transcribe_and_save_lrc(
        str(audio),
        router,
        language="zh",
        use_vocal_separation=True,
        separation_device="cuda",
        progress_callback=events.append,
    )

    assert observed["input"] == str(audio)
    assert observed["device"] == "cuda"
    assert router.calls[0][0] == str(vocals)
    assert any(event.phase == "separate" for event in events)
