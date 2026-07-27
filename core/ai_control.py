"""Restricted CLI bridge used by the in-app AI assistant."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.process_utils import hidden_window_kwargs

CLI_OUTPUT_PATH_ENV = "ECHOVAULT_CLI_OUTPUT_PATH"
_DIRECTIVE = re.compile(r"\[\[ECHOVAULT_CLI:\s*(.+?)\s*\]\]", re.DOTALL)
_UI_DIRECTIVE = re.compile(r"\[\[ECHOVAULT_UI:\s*(.+?)\s*\]\]", re.DOTALL)
_UNSAFE_CHARS = frozenset(";&|><`$")
_UI_TARGETS = {
    "materials",
    "lyrics-online",
    "lyrics-local",
    "lyrics-review",
    "audio",
    "audio-trim",
    "audio-split",
    "audio-volume",
    "audio-denoise",
    "audio-normalize",
    "audio-equalizer",
    "audio-speed-pitch",
    "audio-concat",
    "audio-mix",
    "audio-extract",
    "audio-separate",
    "download",
    "batch",
    "transfer-send",
    "transfer-receive",
    "transfer-sync",
    "models",
    "settings",
    "settings-recognition",
    "settings-lyrics",
    "settings-local-ai",
    "settings-audio-sources",
    "keys",
}
_READ_ONLY = {
    ("list",), ("info",), ("lyrics", "show"), ("lyrics", "search"),
    ("lyrics", "online-search"),
    ("config", "show"), ("config", "path"), ("model", "list"),
    ("model", "info"), ("gpu", "scan"), ("gpu", "status"),
    ("library", "list"), ("video", "timeline"), ("download", "search"),
    ("sync", "compare"), ("cache", "path"), ("doctor",),
}
_MUTATING = {
    ("transcribe",), ("lyrics", "translate"), ("lyrics", "online-apply"),
    ("lyrics", "calibrate"), ("config", "set"), ("model", "download"),
    ("library", "add"), ("library", "remove"), ("library", "select-all"),
    ("video", "transcribe"), ("video", "extract-audio"),
    ("video", "calibrate"), ("video", "aggregate"), ("gpu", "setup"),
    ("audio", "process"), ("audio", "separate"), ("download", "fetch"),
    ("cache", "clear"), ("rename",), ("mark",),
}


@dataclass(frozen=True)
class CLICommand:
    args: tuple[str, ...]
    needs_confirmation: bool


@dataclass(frozen=True)
class UICommand:
    target: str


def allowed_cli_commands() -> dict[str, list[str]]:
    """Return the command prefixes shared by AI and MCP integrations."""
    return {
        "read_only": sorted(" ".join(signature) for signature in _READ_ONLY),
        "mutating": sorted(" ".join(signature) for signature in _MUTATING),
    }


def extract_cli_directives(answer: str) -> tuple[str, list[str]]:
    commands = [match.strip() for match in _DIRECTIVE.findall(answer) if match.strip()]
    return _DIRECTIVE.sub("", answer).strip(), commands


def extract_control_directives(
    answer: str,
) -> tuple[str, list[str], list[str]]:
    """Extract CLI and current-window UI actions from one assistant response."""
    cli_commands = [
        match.strip() for match in _DIRECTIVE.findall(answer) if match.strip()
    ]
    ui_commands = [
        match.strip() for match in _UI_DIRECTIVE.findall(answer) if match.strip()
    ]
    displayed = _UI_DIRECTIVE.sub("", _DIRECTIVE.sub("", answer)).strip()
    return displayed, cli_commands, ui_commands


def validate_ui_command(command: str) -> UICommand:
    parts = command.strip().split()
    if len(parts) != 2 or parts[0] != "open" or parts[1] not in _UI_TARGETS:
        raise ValueError("AI 请求了未授权的界面操作。")
    return UICommand(parts[1])


def _unquote_argument(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def validate_cli_command(
    command: str,
    *,
    current_material: str | None = None,
) -> CLICommand:
    if any(char in command for char in _UNSAFE_CHARS):
        raise ValueError("AI 命令包含不允许的 shell 字符。")
    args = tuple(_unquote_argument(value) for value in shlex.split(command, posix=False))
    if not args:
        raise ValueError("AI 没有提供有效命令。")
    resolved: list[str] = []
    for value in args:
        if value == "@current":
            if not current_material:
                raise ValueError("当前没有选中素材，无法使用 @current。")
            resolved.append(str(Path(current_material).expanduser().resolve()))
        elif value == "@current-dir":
            if not current_material:
                raise ValueError("当前没有选中素材，无法使用 @current-dir。")
            resolved.append(str(Path(current_material).expanduser().resolve().parent))
        else:
            resolved.append(value)
    args = tuple(resolved)
    signature = (args[0], args[1]) if len(args) > 1 else (args[0],)
    if signature in _READ_ONLY:
        return CLICommand(args, needs_confirmation=False)
    if signature in _MUTATING:
        return CLICommand(args, needs_confirmation=True)
    raise ValueError("AI 请求了未授权的 CLI 命令。")


def run_cli_command(command: CLICommand, timeout: int = 180) -> str:
    output_path: Path | None = None
    child_environment = None
    if getattr(sys, "frozen", False):
        invocation = [sys.executable]
        handle, raw_output_path = tempfile.mkstemp(prefix="echovault-cli-", suffix=".log")
        os.close(handle)
        output_path = Path(raw_output_path)
        child_environment = os.environ.copy()
        child_environment[CLI_OUTPUT_PATH_ENV] = raw_output_path
    else:
        invocation = [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py")]
    try:
        completed = subprocess.run(
            [*invocation, *command.args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=child_environment,
            **hidden_window_kwargs(),
        )
        captured = ""
        if output_path is not None and output_path.exists():
            captured = output_path.read_text(encoding="utf-8", errors="replace")
        output = (captured or completed.stdout or completed.stderr).strip()
        if completed.returncode:
            raise RuntimeError(output or f"CLI 返回错误码 {completed.returncode}。")
        return output or "命令执行完成。"
    finally:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
