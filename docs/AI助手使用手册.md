# Echovault AI 助手使用手册

AI 模式默认使用 DeepSeek 的 OpenAI 兼容接口：`https://api.deepseek.com`，默认模型为 `deepseek-chat`。

启动前在“密钥管理”填写 DeepSeek API Key。启动 AI 模式后，最左侧会出现聊天栏。聊天请求始终附带内置系统提示词和本手册所覆盖的软件知识，包括素材库、歌词识别、本地模型、Groq、视频时间校准、同步、隐私和 CLI。

AI 助手可介绍软件、解释当前功能和给出操作步骤；它不会在没有明确功能支持时假装执行动作。AI 模式不启用时不会发起 DeepSeek 请求。

命令行等价入口：

```powershell
python main.py ai chat "如何给视频校准时间？"
```
