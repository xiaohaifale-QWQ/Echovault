from types import SimpleNamespace

import pytest

from core.ai_control import (
    CLI_OUTPUT_PATH_ENV,
    extract_cli_directives,
    run_cli_command,
    validate_cli_command,
)


def test_ai_cli_directive_is_extracted_and_read_only_is_allowed():
    text, commands = extract_cli_directives("正在检查。\n[[ECHOVAULT_CLI: config show]]")

    assert text == "正在检查。"
    assert commands == ["config show"]
    assert validate_cli_command(commands[0]).needs_confirmation is False


def test_ai_cli_mutation_requires_confirmation_and_shell_is_rejected():
    assert validate_cli_command("cache clear").needs_confirmation is True
    assert (
        validate_cli_command("lyrics translate song.lrc --engine local").needs_confirmation
        is True
    )
    with pytest.raises(ValueError, match="shell"):
        validate_cli_command("config show; whoami")


def test_frozen_cli_output_is_returned_from_windowed_capture(monkeypatch):
    command = validate_cli_command("config show")
    monkeypatch.setattr("core.ai_control.sys.frozen", True, raising=False)

    def fake_run(_args, **kwargs):
        output_path = kwargs["env"][CLI_OUTPUT_PATH_ENV]
        with open(output_path, "w", encoding="utf-8") as output:
            output.write('{"ready": true}')
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("core.ai_control.subprocess.run", fake_run)

    assert run_cli_command(command) == '{"ready": true}'
