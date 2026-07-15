# Echovault MCP 接口使用指南

Echovault MCP Server 把现有 CLI 白名单包装成标准 Model Context Protocol 工具，使 Codex、Claude、Cursor 和其他 MCP 客户端能够读取素材库状态并在用户授权后执行操作。

## 1. 安装

```powershell
cd E:\music\music-lyrics-sync
python -m pip install -r requirements-mcp.txt
```

当前固定使用官方 Python SDK `mcp>=1.27,<2`。MCP v2 进入稳定版后应先阅读迁移说明、运行回归测试，再调整版本范围。

## 2. stdio 模式

stdio 适合由桌面 AI 客户端直接启动：

```powershell
python E:\music\music-lyrics-sync\mcp_server.py
```

客户端配置示例：

```json
{
  "mcpServers": {
    "echovault": {
      "command": "C:\\Users\\32570\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": ["E:\\music\\music-lyrics-sync\\mcp_server.py"]
    }
  }
}
```

默认不允许任何写操作。

## 3. Streamable HTTP 模式

```powershell
python mcp_server.py --transport streamable-http --host 127.0.0.1 --port 8765
```

MCP 端点为 `http://127.0.0.1:8765/mcp`。默认只监听本机；除非已经配置防火墙、认证和可信局域网，不要改为 `0.0.0.0`。

## 4. 工具

### `echovault_capabilities`

返回只读命令、写命令、当前写权限和安全策略。

### `echovault_execute`

参数：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `command` | string | 一条 Echovault CLI 命令，不含 `python main.py` |
| `confirmed` | boolean | 用户是否明确确认本次写操作；只读命令可省略 |

读取示例：

```json
{"command":"config show"}
```

写操作采用两道门：

1. 服务必须由用户以 `--allow-writes` 启动。
2. 每次写调用必须带 `confirmed: true`。

```powershell
python mcp_server.py --allow-writes
```

```json
{"command":"library add E:\\music --mode music","confirmed":true}
```

缺少任一授权时只返回 `writes_disabled` 或 `confirmation_required`，不会执行命令。

## 5. 权限边界

- MCP 与内置 AI 共用 `core/ai_control.py` 的白名单。
- 命令使用参数数组启动，永不使用 `shell=True`。
- 拒绝分号、管道、重定向、反引号和美元符号等 shell 注入字符。
- `config show` 只返回密钥是否已配置，不返回密钥内容。
- 不开放 `serve`、任意程序、PowerShell、cmd 或递归 AI 调用。
- 新增 MCP 写能力时必须同时更新 CLI 白名单、确认分类、测试和本文档。

## 6. 返回结构

| `status` | 含义 |
| --- | --- |
| `ok` | 已成功执行，`result` 为 JSON 或文本 |
| `rejected` | 命令不在白名单或包含危险字符 |
| `writes_disabled` | 服务器未以 `--allow-writes` 启动 |
| `confirmation_required` | 本次写操作尚未得到确认 |
| `error` | CLI 返回错误，详情在 `error` 字段 |

## 7. 验证

```powershell
pytest tests\test_mcp_bridge.py tests\test_ai_control.py -q
python mcp_server.py --help
npx -y @modelcontextprotocol/inspector
```

使用 Inspector 时，stdio 模式填写 Python 命令和脚本参数；HTTP 模式连接 `http://127.0.0.1:8765/mcp`。
