"""Restricted CLI bridge used by the in-app AI assistant."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core.process_utils import hidden_window_kwargs

_DIRECTIVE = re.compile(r"\[\[ECHOVAULT_CLI:\s*(.+?)\s*\]\]", re.DOTALL)
_UNSAFE_CHARS = frozenset(";&|><`$")
_READ_ONLY = {
    ("list",), ("info",), ("lyrics", "show"), ("lyrics", "search"),
    ("config", "show"), ("config", "path"), ("model", "list"),
    ("model", "info"), ("gpu", "scan"), ("gpu", "status"),
    ("library", "list"), ("video", "timeline"), ("cache", "path"), ("doctor",),
}
_MUTATING = {
    ("transcribe",), ("config", "set"), ("model", "download"),
    ("library", "add"), ("library", "remove"), ("library", "select-all"),
    ("video", "calibrate"), ("video", "aggregate"), ("cache", "clear"),
    ("rename",), ("mark",),
}


@dataclass(frozen=True)
class CLICommand:
    args: tuple[str, ...]
    needs_confirmation: bool


def extract_cli_directives(answer: str) -> tuple[str, list[str]]:
    commands = [match.strip() for match in _DIRECTIVE.findall(answer) if match.strip()]
    return _DIRECTIVE.sub("", answer).strip(), commands


def validate_cli_command(command: str) -> CLICommand:
    if any(char in command for char in _UNSAFE_CHARS):
        raise ValueError("AI 命令包含不允许的 shell 字符。")
    args = tuple(shlex.split(command, posix=False))
    if not args:
        raise ValueError("AI 没有提供有效命令。")
    signature = (args[0], args[1]) if len(args) > 1 else (args[0],)
    if signature in _READ_ONLY:
        return CLICommand(args, needs_confirmation=False)
    if signature in _MUTATING:
        return CLICommand(args, needs_confirmation=True)
    raise ValueError("AI 请求了未授权的 CLI 命令。")


def run_cli_command(command: CLICommand, timeout: int = 180) -> str:
    if getattr(sys, "frozen", False):
        invocation = [sys.executable]
    else:
        invocation = [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py")]
    completed = subprocess.run(
        [*invocation, *command.args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **hidden_window_kwargs(),
    )
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode:
        raise RuntimeError(output or f"CLI 返回错误码 {completed.returncode}。")
    return output or "命令执行完成。"
