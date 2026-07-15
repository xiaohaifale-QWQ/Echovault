"""Safe MCP-facing adapter around Echovault's existing CLI whitelist."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from core.ai_control import (
    CLICommand,
    allowed_cli_commands,
    run_cli_command,
    validate_cli_command,
)


def mcp_capabilities(*, allow_writes: bool = False) -> dict[str, Any]:
    """Describe commands and the two-step write authorization policy."""
    commands = allowed_cli_commands()
    return {
        "name": "Echovault",
        "read_only_commands": commands["read_only"],
        "mutating_commands": commands["mutating"],
        "writes_enabled": allow_writes,
        "write_policy": (
            "写操作需要服务器以 --allow-writes 启动，且每次工具调用 confirmed=true。"
        ),
    }


def execute_mcp_command(
    command: str,
    *,
    confirmed: bool = False,
    allow_writes: bool = False,
    runner: Callable[[CLICommand], str] = run_cli_command,
) -> dict[str, Any]:
    """Validate and execute one CLI command without ever invoking a shell."""
    try:
        validated = validate_cli_command(command)
    except ValueError as exc:
        return {"status": "rejected", "command": command, "error": str(exc)}

    if validated.needs_confirmation and not allow_writes:
        return {
            "status": "writes_disabled",
            "command": command,
            "error": "MCP 服务未启用写操作；请由用户使用 --allow-writes 重新启动。",
        }
    if validated.needs_confirmation and not confirmed:
        return {
            "status": "confirmation_required",
            "command": command,
            "error": "该命令会修改配置、文件或缓存，需要用户明确确认。",
        }

    try:
        output = runner(validated)
    except (OSError, RuntimeError) as exc:
        return {"status": "error", "command": command, "error": str(exc)}

    try:
        result: Any = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        result = output
    return {
        "status": "ok",
        "command": command,
        "mutating": validated.needs_confirmation,
        "result": result,
    }
