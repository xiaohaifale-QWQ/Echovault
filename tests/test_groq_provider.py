from types import SimpleNamespace

from core.asr.groq_whisper import GroqWhisperProvider


class FakeTranscriptions:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_groq_provider_accepts_sdk_segment_objects(tmp_path):
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"wav")
    response = SimpleNamespace(
        language="zh",
        duration=3.0,
        segments=[SimpleNamespace(start=0.5, end=2.0, text=" 歌词 ", avg_logprob=-0.2)],
    )
    transcriptions = FakeTranscriptions(response)
    provider = GroqWhisperProvider(api_key="test")
    provider._client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=transcriptions)
    )

    result = provider.transcribe(str(audio), language="zh")

    assert result.language == "zh"
    assert result.duration == 3.0
    assert result.segments[0].start_time == 0.5
    assert result.segments[0].text == "歌词"
    assert transcriptions.kwargs["model"] == "whisper-large-v3"
