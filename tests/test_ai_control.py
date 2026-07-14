import pytest

from core.ai_control import extract_cli_directives, validate_cli_command


def test_ai_cli_directive_is_extracted_and_read_only_is_allowed():
    text, commands = extract_cli_directives("正在检查。\n[[ECHOVAULT_CLI: config show]]")

    assert text == "正在检查。"
    assert commands == ["config show"]
    assert validate_cli_command(commands[0]).needs_confirmation is False


def test_ai_cli_mutation_requires_confirmation_and_shell_is_rejected():
    assert validate_cli_command("cache clear").needs_confirmation is True
    with pytest.raises(ValueError, match="shell"):
        validate_cli_command("config show; whoami")
