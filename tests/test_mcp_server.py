import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _stdio_roundtrip() -> None:
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "mcp_server.py")],
        cwd=str(root),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=10)
            tools = await asyncio.wait_for(session.list_tools(), timeout=10)
            assert [tool.name for tool in tools.tools] == [
                "echovault_capabilities",
                "echovault_execute",
            ]

            result = await asyncio.wait_for(
                session.call_tool("echovault_execute", {"command": "config show"}),
                timeout=10,
            )
            assert result.isError is False
            assert result.content


def test_mcp_stdio_client_can_list_and_call_tools():
    asyncio.run(_stdio_roundtrip())
