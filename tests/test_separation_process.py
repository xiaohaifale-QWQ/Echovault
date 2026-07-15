import io
import json
from pathlib import Path

from core import separation_process


def test_run_separation_process_reads_live_result(monkeypatch, tmp_path):
    vocals = tmp_path / "song_vocals.wav"
    vocals.write_bytes(b"wav")
    events = []

    class FakeProcess:
        returncode = 0
        stderr = io.StringIO("")

        def __init__(self, command, **_kwargs):
            events_path = Path(command[command.index("--events-file") + 1])
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {"type": "progress", "percent": 50, "message": "GPU"}
                        ),
                        json.dumps(
                            {
                                "type": "result",
                                "vocals_path": str(vocals),
                                "accompaniment_path": None,
                                "sample_rate": 44100,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        def poll(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(separation_process.subprocess, "Popen", FakeProcess)

    result = separation_process.run_separation_process(
        tmp_path / "song.wav",
        tmp_path,
        model="htdemucs",
        device="cuda",
        output_content="vocals",
        progress=lambda percent, message: events.append((percent, message)),
    )

    assert result.vocals_path == vocals
    assert result.accompaniment_path is None
    assert events == [(50, "GPU")]
