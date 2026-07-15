"""MCP server exposing Echovault's validated CLI bridge."""

from __future__ import annotations

import argparse
import asyncio
from functools import partial

from core.mcp_bridge import execute_mcp_command, mcp_capabilities

SERVER_INSTRUCTIONS = """Echovault 音频/视频素材与歌词工具。
只能执行服务器公布的 Echovault CLI 白名单；禁止 shell、管道和外部程序。
默认只读。写操作必须由用户以 --allow-writes 启动服务器，并逐次确认。
"""


def build_server(*, allow_writes: bool, host: str, port: int):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "未安装 MCP 依赖。请运行: pip install -r requirements-mcp.txt"
        ) from exc

    server = FastMCP(
        "Echovault",
        instructions=SERVER_INSTRUCTIONS,
        json_response=True,
        host=host,
        port=port,
    )

    @server.tool()
    def echovault_capabilities() -> dict:
        """列出当前 MCP 服务允许的只读/写入命令及权限状态。"""
        return mcp_capabilities(allow_writes=allow_writes)

    @server.tool()
    async def echovault_execute(command: str, confirmed: bool = False) -> dict:
        """执行一条白名单内命令；写操作必须由用户确认。"""
        return await asyncio.to_thread(
            partial(
                execute_mcp_command,
                command,
                confirmed=confirmed,
                allow_writes=allow_writes,
            )
        )

    @server.resource("echovault://capabilities")
    def capabilities_resource() -> dict:
        """机器可读的 Echovault CLI 能力清单。"""
        return mcp_capabilities(allow_writes=allow_writes)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Echovault MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="允许经过白名单校验且逐次确认的写操作",
    )
    args = parser.parse_args()

    server = build_server(
        allow_writes=args.allow_writes,
        host=args.host,
        port=args.port,
    )
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
