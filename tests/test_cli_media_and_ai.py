import argparse
import json
from pathlib import Path

import main
from core.ai_control import (
    extract_control_directives,
    validate_cli_command,
    validate_ui_command,
)


class _Provider:
    display_name = "Test ASR"

    @staticmethod
    def is_available():
        return True


class _Router:
    @staticmethod
    def get(_name):
        return _Provider()


def _transcribe_args(target: Path, **overrides):
    values = {
        "target": str(target),
        "provider": "local",
        "language": "zh",
        "force": False,
        "output_dir": None,
        "json_output": True,
        "quiet": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_transcribe_accepts_video_and_reports_material_type(
    monkeypatch, tmp_path, capsys
):
    video = tmp_path / "meeting.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "meeting.lrc"
    monkeypatch.setattr(main, "get_router", lambda _config: _Router())
    monkeypatch.setattr(
        main,
        "transcribe_and_save_lrc",
        lambda **_kwargs: str(output),
    )

    main.cmd_transcribe(_transcribe_args(video))

    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"] == {
        "total": 1,
        "ok": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert payload["results"][0]["material_type"] == "video"
    assert payload["results"][0]["path"] == str(video.resolve())


def test_video_extract_audio_uses_asr_wav_contract(monkeypatch, tmp_path, capsys):
    video = tmp_path / "meeting.mkv"
    video.write_bytes(b"video")
    output = tmp_path / "meeting.asr.wav"
    converted = []
    monkeypatch.setattr(
        main,
        "convert_to_whisper_format",
        lambda source, target: converted.append((source, target)),
    )
    args = argparse.Namespace(
        video_action="extract-audio",
        input=str(video),
        output=str(output),
        force=False,
        json_output=True,
    )

    main.cmd_video(args)

    assert converted == [(str(video.resolve()), str(output.resolve()))]
    payload = json.loads(capsys.readouterr().out)
    assert payload["sample_rate"] == 16000
    assert payload["channels"] == 1


def test_ai_control_resolves_current_material_without_shell():
    command = validate_cli_command(
        "video transcribe @current --provider local --json",
        current_material=r"C:\资料\会议 视频.mp4",
    )

    assert command.needs_confirmation
    assert command.args[2] == str(Path(r"C:\资料\会议 视频.mp4").resolve())
    assert command.args[:2] == ("video", "transcribe")


def test_ai_control_exposes_audio_download_and_gpu_operations():
    assert not validate_cli_command("download search 再见 --json").needs_confirmation
    assert validate_cli_command(
        'audio process volume --input "C:\\music\\a.mp3" '
        '--output "C:\\music\\a_new.mp3" --params-json "{\\"gain_db\\":3}"'
    ).needs_confirmation
    assert validate_cli_command("gpu setup --json").needs_confirmation


def test_ai_control_extracts_and_restricts_current_window_navigation():
    displayed, cli_commands, ui_commands = extract_control_directives(
        "已为你打开。[[ECHOVAULT_UI: open audio-separate]]"
    )

    assert displayed == "已为你打开。"
    assert cli_commands == []
    assert ui_commands == ["open audio-separate"]
    assert validate_ui_command(ui_commands[0]).target == "audio-separate"
