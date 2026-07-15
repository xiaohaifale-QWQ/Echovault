from core.mcp_bridge import execute_mcp_command, mcp_capabilities


def test_mcp_capabilities_default_to_read_only():
    capabilities = mcp_capabilities()

    assert capabilities["writes_enabled"] is False
    assert "config show" in capabilities["read_only_commands"]
    assert "config set" in capabilities["mutating_commands"]
    assert "lyrics translate" in capabilities["mutating_commands"]
    assert "lyrics online-search" in capabilities["read_only_commands"]
    assert "lyrics online-apply" in capabilities["mutating_commands"]
    assert "lyrics calibrate" in capabilities["mutating_commands"]


def test_mcp_rejects_shell_and_requires_two_step_write_authorization():
    called = []

    def runner(command):
        called.append(command)
        return "done"

    assert execute_mcp_command("config show; whoami", runner=runner)["status"] == "rejected"
    assert execute_mcp_command("cache clear", runner=runner)["status"] == "writes_disabled"
    assert (
        execute_mcp_command("cache clear", allow_writes=True, runner=runner)["status"]
        == "confirmation_required"
    )
    assert called == []

    result = execute_mcp_command(
        "cache clear",
        allow_writes=True,
        confirmed=True,
        runner=runner,
    )
    assert result["status"] == "ok"
    assert result["mutating"] is True
    assert len(called) == 1


def test_mcp_returns_parsed_json_for_read_only_commands():
    result = execute_mcp_command(
        "config show",
        runner=lambda _command: '{"ready": true}',
    )

    assert result == {
        "status": "ok",
        "command": "config show",
        "mutating": False,
        "result": {"ready": True},
    }
