# Echovault AI 助手使用手册

AI 模式默认使用 DeepSeek 的 OpenAI 兼容接口：`https://api.deepseek.com`，默认模型为 `deepseek-chat`。

启动前在“密钥管理”填写 DeepSeek API Key。启动 AI 模式后，主内容区右侧会在顶部操作栏下方展开 280px 紧凑聊天抽屉，不会覆盖窗口标题、品牌、全局搜索或顶部按钮。聊天请求始终附带内置系统提示词和本手册所覆盖的软件知识，包括素材库、歌词识别、本地模型、Groq、视频时间校准、同步、隐私和 CLI。

AI 助手可介绍软件、解释当前功能和给出操作步骤；它不会在没有明确功能支持时假装执行动作。AI 模式不启用时不会发起 DeepSeek 请求。

AI 助手也可以执行自然语言操作。当前选中的音乐或视频会作为上下文传给 AI，AI 使用受控的 `@current` 占位符发起 CLI 操作；读取操作直接执行，识别、下载、编辑、模型/CUDA 安装、配置和文件修改都会先显示实际命令并让用户确认。音频编辑始终另存新文件。

命令行等价入口：

```powershell
python main.py ai chat "如何给视频校准时间？"
```

完整命令、视频转写、模型下载、CUDA 运行时和外部 Agent/MCP 接入见 [AI 调用 CLI 与 CUDA 使用指南](AI调用CLI与CUDA使用指南.md)。
