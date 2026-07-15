# Echovault AI 接口与本地模型接入指南

本文说明 Echovault 内置 AI 助手的在线接口、本地部署接口、配置字段、请求格式和安全边界。AI 对话与 MCP 是两层不同能力：AI 接口负责生成回答，MCP 接口负责让外部 AI 在白名单内操作 Echovault。

## 1. 支持的接口

Echovault 发送 OpenAI 兼容的 Chat Completions 请求：

```text
POST {base_url}/chat/completions
Content-Type: application/json
Authorization: Bearer {api_key}   # 只有配置了 Key 时才发送
```

请求体示例：

```json
{
  "model": "qwen3:8b",
  "messages": [
    {"role": "system", "content": "Echovault 内置使用手册与系统提示词"},
    {"role": "user", "content": "如何使用本地识别？"}
  ],
  "temperature": 0.3
}
```

服务至少需要返回以下结构：

```json
{
  "choices": [
    {"message": {"content": "回答内容"}}
  ]
}
```

当前不依赖流式响应、工具调用或厂商私有字段，因此 Ollama、LM Studio 以及实现上述协议的其他服务均可接入。

## 2. 在线 AI

默认在线配置为：

- 接口地址：`https://api.deepseek.com`
- 模型：`deepseek-chat`
- Key：顶栏“密钥管理”中的 DeepSeek API Key

在线 AI 必须填写 Key。密钥只保存在当前用户的 `~/.music-lyrics-sync/config.json`，不会写入项目或正常日志。

## 3. 本地部署 AI

1. 启动本地模型服务，并确认它已加载一个聊天模型。
2. 打开“设置 → 本地部署 AI”。
3. 把“AI 来源”切换为“本地部署 AI”。
4. 选择预设或填写接口地址与模型名称。
5. 保存设置，再从顶栏启动“AI 模式”。

本地接口的 API Key 是可选项；未填写时请求不会带 `Authorization` 请求头。

### Ollama

默认预设：

```text
接口地址：http://127.0.0.1:11434/v1
模型名称：填写 `ollama list` 中存在的模型，例如 qwen3:8b
API Key：留空
```

服务必须先在本机运行，模型名称必须与服务端名称完全一致。Echovault 不负责启动 Ollama 或自动下载其模型。

### LM Studio

默认预设：

```text
接口地址：http://127.0.0.1:1234/v1
模型名称：填写 LM Studio 已加载模型的 API 标识
API Key：通常留空
```

需要先在 LM Studio 的 Developer/Local Server 页面加载模型并启动服务。如果用户修改了监听端口，应同步修改 Echovault 地址。

### 其他兼容服务

接口根地址应包含服务要求的 `/v1`，但不要在末尾填写 `/chat/completions`。例如：

```text
正确：http://192.168.1.20:8000/v1
错误：http://192.168.1.20:8000/v1/chat/completions
```

如果服务启用了鉴权，在可选 API Key 中填写 Token；软件会发送 `Bearer` 鉴权。

## 4. 配置字段与环境变量

| 配置项 | CLI Key | 环境变量 | 说明 |
| --- | --- | --- | --- |
| AI 来源 | `ai_provider` | — | `online` 或 `local` |
| 在线 Key | `ai_model_api_key` | `ECHOVAULT_AI_API_KEY` | 在线 AI 必填 |
| 在线地址 | `ai_base_url` | — | 默认 DeepSeek |
| 在线模型 | `ai_model_name` | — | 默认 `deepseek-chat` |
| 本地 Key | `local_ai_api_key` | `ECHOVAULT_LOCAL_AI_API_KEY` | 可选 |
| 本地地址 | `local_ai_base_url` | `ECHOVAULT_LOCAL_AI_BASE_URL` | 默认 Ollama |
| 本地模型 | `local_ai_model_name` | `ECHOVAULT_LOCAL_AI_MODEL` | 本地模式必填 |

CLI 配置示例：

```powershell
python main.py config set ai_provider local
python main.py config set local_ai_base_url http://127.0.0.1:11434/v1
python main.py config set local_ai_model_name qwen3:8b
python main.py config show --json
python main.py ai chat "请介绍当前素材库的使用方式" --json
```

`config show --json` 只返回 Key 是否已配置，不返回 Key 明文。`config set local_ai_api_key ...` 的终端回显也会被遮罩。

环境变量优先于配置文件，适合不希望落盘保存本地网关 Token 的部署。修改环境变量后需要重启 Echovault。

## 5. 故障排查

- “未配置本地 AI 模型名称”：填写服务端实际加载的模型 ID，而不是软件显示名。
- “无法连接本地 AI 服务”：确认服务正在运行、端口一致，并检查 Windows 防火墙；远端局域网地址还需确认服务监听的不是仅本机回环地址。
- HTTP 401/403：服务要求 Key，或当前 Key 没有权限。
- HTTP 404：通常是接口根地址填写错误；地址应停在 `/v1`，不要重复填写 `/chat/completions`。
- “返回了无法解析的响应”：兼容服务没有返回 `choices[0].message.content`。
- 请求很慢：由模型大小、上下文长度和本机算力决定；Echovault 当前单次请求超时为 60 秒。

## 6. 安全边界

- 不要把监听在 `0.0.0.0` 的无鉴权本地模型端口直接暴露到公网。
- AI 生成的 CLI 指令仍经过 Echovault 严格白名单；写操作仍需要用户确认。
- MCP 默认只读。启用 MCP 写操作需要服务器启动时允许写入，并由每次调用再次确认。
- 项目提交、测试夹具和文档中不得放入真实 Token。

MCP 的安装、客户端配置与完整权限模型见 [MCP 接口使用指南](MCP接口使用指南.md)。

## 7. 官方参考

- [Ollama：OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [LM Studio：本地 API Server](https://lmstudio.ai/docs/developer/core/server)
- [Model Context Protocol：Python SDK](https://github.com/modelcontextprotocol/python-sdk)
