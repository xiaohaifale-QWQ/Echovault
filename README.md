# Echovault / 琳琅乐府

本地优先的音频、视频素材库与 AI 歌词识别桌面软件。它把素材浏览、LRC 生成与编辑、离线 Whisper、Groq 在线识别、视频时间校准和 LocalSend 同步放在同一个 Windows 桌面程序中。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-green)](https://riverbankcomputing.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 适用场景

- 为本地音乐批量生成带时间戳的 `.lrc` 歌词。
- 管理录音、音乐和视频素材；视频会先提取音轨，再走同一套 Whisper 识别流程。
- 根据视频拍摄时间把识别到的文字映射到真实日期时间。
- 在不上传音频的前提下使用本地 Whisper；或使用 Groq 获得更快的云端识别。
- 通过 LocalSend 从手机无线收取素材，处理后查看新增/修改结果并选送回手机。

## 功能一览

| 模块 | 功能 |
| --- | --- |
| 统一工作区 | 顶部提供全局搜索、批量任务、模型库和设置；左侧只保留四个任务入口，并在底部用紧凑卡片显示当前歌名和同步滚动歌词；AI 仅在启动后从右侧展开。 |
| 素材库 | 音乐、视频两种互斥模式；文件夹独立保存；使用单个 Windows 资源管理器式目录树，右上角加号添加根目录，双击展开、单击选择并支持 Ctrl/Shift 多选，右侧合并显示所有选中目录的素材。 |
| 歌词识别 | Groq Whisper 在线识别与本地 Whisper 离线识别；批量任务显示真实已完成数量，单个素材显示当前阶段和等待状态。 |
| 本地模型 | `tiny`、`base`、`small`、`medium` 模型从项目 Release 下载，支持续传、SHA-256 校验、分片合并和临时文件清理。 |
| 人声分离 | Demucs 本地分离人声与伴奏；统一模型库、双波形同步试听、独立音量和无损混音导出，也可在本地识别前先提取人声。 |
| 音频编辑 | 11 个独立工作台支持裁剪、分段、增益、降噪、响度、均衡、变速变调、拼接、混合、提取和标签；波形后台解码并缓存，隐藏页面按需加载。 |
| GPU | 自动诊断显卡与运行时；可安装并启用匹配的外置 GPU 推理运行时，无法使用时安全回退 CPU。 |
| 视频时间 | 读取视频时间元数据；左、右时间可精确编辑到秒；使用小时偏移快速校准并导出视频文字时间轴。 |
| 歌词与标签 | 按“在线歌词与封面、本地识别编辑、歌词核对”三个独立工作流组织；支持 LRCLIB 歌词、Apple 快速封面及 MusicBrainz/CAA 回退、同步播放器、音频标签编辑与 AI 校准。 |
| 密钥管理 | 从顶部“设置”集中管理 Groq、讯飞和 DeepSeek Key；Key 仅保存在当前 Windows 用户的本机配置中。 |
| AI 助手 | 默认隐藏，启动后在顶部工具栏下方从右侧展开为 280px 紧凑抽屉；可切换 DeepSeek 或本地 OpenAI 兼容模型，并在每次对话中加载内置使用手册与系统提示词。 |

应用内实行单一播放焦点：在线歌词、歌词核对、音频工作台和人声分离之间切换试听时，
新播放器会自动暂停上一界面的播放器；人声分离的人声与伴奏仍作为一组同步播放。
| 手机传输 | LocalSend 双向传输；按接收批次记录原始文件，自动发现处理结果，可查看、勾选并发送回手机。传统文件夹同步保留在高级区域。 |
| CLI | 支持识别、配置、模型、GPU 和环境诊断命令，并提供 JSON 输出。 |

## 隐私与网络

- 使用本地 Whisper 时，音频与模型均在本机处理。
- 使用 Groq 在线识别时，待识别音频会发送给 Groq API；请只对允许上传的素材使用该模式。
- API Key 不写入项目、源码、Git 或日志，保存在 `~/.music-lyrics-sync/config.json`。该文件属于当前 Windows 用户，应妥善保护。
- AI 模式默认调用 DeepSeek；切换到本地 AI 后只访问用户填写的本地兼容接口。

## 快速开始（源码运行）

```powershell
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault

python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Groq 在线识别 + 桌面程序
pip install -r requirements-cloud.txt

# 如需源码环境中的本地 Whisper，再安装：
pip install -r requirements-local.txt

# ffmpeg 与 ffprobe 必须在 PATH 中
winget install Gyan.FFmpeg

python main.py doctor
python main.py
```

## Windows 打包与启动

构建会自动检查 `ffmpeg`、`ffprobe`、PyInstaller 与 Groq SDK，并把所需的 Groq 子模块一起打入发布目录。

```powershell
.\build.ps1 -Python "C:\Path\To\python.exe"
.\dist\Echovault\Echovault.exe
```

## 使用指南

### 1. 添加素材

1. 打开左侧“素材”工作区。
2. 在“音乐模式”或“视频模式”下点击右上角“＋”。两种模式的文件夹完全独立，新增目录会成为目录树的最上级文件夹。
3. 双击文件夹可在同一棵目录树中展开下级；单击选择一个目录，按住 Ctrl 或 Shift 可多选，右侧素材列表会合并显示所有选中目录中的内容。
4. 从右侧选择音频或视频后开始识别。左侧导航底部会显示当前歌名，并跟随任一播放器实时滚动同步歌词；视频会自动抽取音轨，输出仍使用标准 LRC 时间轴。

### 2. 选择识别引擎

点击顶部“模型库”：

- **在线识别模型**：直接选择 Groq Whisper 或讯飞云端识别；缺少密钥时可跳转“密钥管理”。
- **本地 Whisper 模型**：下载 Tiny、Base、Small 或 Medium，下载完成后直接设为当前模型；音频不离开电脑。
- **音频分离与增强模型**：管理 Demucs、UVR、默认分离模型和 GPU 偏好。

“设置 → 语音识别”不再重复选择模型，只保留默认语言、人声分离和本地 GPU
运行时参数。Groq 连接失败时会区分 Key 无效、调用额度不足和
`api.groq.com:443` 网络/TLS 超时，便于定位原因。

### 3. 管理 API Key

点击顶部“设置 → 密钥管理”：

- **Groq API Key**：用于 Groq 在线转写。
- **Groq 代理地址（可选）**：直连无法访问 Groq 时，可填写正在运行的本地 HTTP 代理，例如 `http://127.0.0.1:7890`。
- **讯飞云端识别**：在密钥管理中填写同一讯飞应用的 `AppID`、`API Key`、`API Secret`。Echovault 优先使用“极速录音转写”；若当前 AppID 未开通该产品或当日额度耗尽，会自动改用通常默认带有调用额度的“语音听写（流式版）”。流式模式会把音频按不超过 50 秒分段并行识别，再合并为完整时间轴；两种模式都会把音频上传到讯飞云端。
- **DeepSeek API Key**：用于内置 AI 助手。默认接口为 `https://api.deepseek.com`，默认模型为 `deepseek-chat`，也可在密钥管理中改为其他 OpenAI 兼容接口。

保存密钥不会自动改变当前识别模型；请在模型库点击“使用”。清空某一项并保存即可删除该本机 Key。

### 4. AI 模式

点击顶部“设置 → 启动 AI 助手”。在线模式需先填写 DeepSeek Key；本地模式在“设置 → 本地部署 AI”中选择 Ollama、LM Studio 预设或自定义 OpenAI 兼容接口，并填写模型名称，本地 Key 可留空。AI 会在标题栏和顶部操作区下方从主内容区右侧展开为紧凑抽屉，不遮挡品牌、全局搜索和顶部按钮；再次点击“设置 → 关闭 AI 助手”即可收起。

完整请求格式、配置字段与故障排查见 [AI 接口与本地模型接入指南](docs/AI接口与本地模型接入指南.md)。

详情页还可使用当前 AI 接口在线翻译，或在“设置 → 歌词输出”下载 Argos 语言包后完全离线翻译；批量翻译会自动检测每份歌词的源语言，译文使用独立语言后缀，不覆盖原 LRC。参见 [歌词翻译使用指南](docs/歌词翻译使用指南.md)。

切到左侧“歌词与标签”后，默认先进入“在线歌词与封面”：顶部紧凑搜索卡内可一键并行请求歌词和封面；LRCLIB 精确歌词可先显示，完整候选在后台补齐；封面优先走单请求快速源，MusicBrainz/CAA 作为回退。“在线歌词”模块采用可拖动左右分栏，候选表在左、歌词正文在右，同步播放器横跨两栏底部；页面最右侧通过“封面候选 / 音频标签”两个页签切换，标签页提供标题、歌手、专辑、年份和轨道号且保存按钮始终可见。相同查询缓存 10 分钟，封面候选先出现、缩略图再并发载入。“本地识别编辑”负责离线识别、编辑与翻译，“歌词核对”提供本地/在线双栏对照、试听、合并和 AI 校准。参见 [在线歌词匹配与 AI 校准指南](docs/在线歌词匹配与AI校准指南.md)。

### 5. 视频时间校准与汇总

视频模式中选择参考视频后：

1. 左侧默认显示视频读取到的起始时间，可直接输入 `年月日 时:分:秒`。
2. 单击中间横杠，选择常用的“向后推 N 小时”。
3. 双击横杠，输入任意小时数；负数表示向前推。右侧会自动显示计算后的真实时间。
4. 修改左侧时间时，右侧会保留已选小时偏移自动重算。
5. 使用“汇总”或“导出”在当前素材文件夹的子目录中生成按时间排列的结果与 `视频文字时间轴.csv`。

### 6. 模型下载

本地模型由软件从独立 Release 下载：

<https://github.com/xiaohaifale-QWQ/echovault-models/releases/tag/v1.0>

下载器支持断点续传与完整性校验。`medium` 模型由两个分片组成，软件会校验、合并为完整模型并清理不再需要的分片；下载与合并时请预留约 6 GB 可用空间。

### 7. 人声与伴奏分离

打开左侧“音频编辑”，进入“人声分离”子页，从统一模型库安装 HTDemucs 后即可处理当前音乐或视频素材。处理设置
位于上方，双波形试听和调音位于下方；人声、伴奏会分别保存为无损 WAV，调音后的合成结果
另存为新文件，不修改原素材。完整说明见
[人声与伴奏分离使用指南](docs/人声与伴奏分离使用指南.md)。

### 8. 手机传入、处理并回传

1. 打开左侧“导出与传输 → 接收”，选择接收目录并点击“开启接收”。
2. 在手机 LocalSend 中选择设备 `Echovault` 并发送素材；每次发送会建立独立任务。
3. 使用歌词识别、翻译、人声分离或视频汇总处理任务中的素材。
4. 返回“导出与传输 → 发送”并刷新结果；新生成和已修改文件会默认加入回传选择。
5. 双击文件可查看文本差异或媒体信息。打开手机 LocalSend，选择发现到的手机后发送。

“导出与传输”固定拆分为“发送、接收、批量任务、高级文件夹同步”四个页面；A/B
目录同步不再折叠在手机传输页面底部。

处理结果会在素材目录的 `Echovault输出\待回传` 建立回传副本；同一磁盘优先使用
NTFS 硬链接，避免大型 WAV 重复占用空间。发送成功后，回传副本移入应用的
`cache\sent-transfer` 缓存并从传输列表隐藏。可在“设置 → 缓存”查看文件数量、
总大小或清理已发送缓存；正式处理结果和待回传文件不会被缓存清理删除。

手机上的最终保存目录由手机 LocalSend 设置和系统权限决定，电脑端不能指定手机任意目录。
完整说明见 [手机双向传输使用指南](docs/手机双向传输使用指南.md)。

### 9. 音频编辑

选择素材后打开左侧“音频编辑”。左侧用于选择工具，右侧整个区域会切换为该工具自己的
完整工作台，不再让所有功能共用同一条波形和参数栏：

- 基础编辑：裁剪与淡化、分段导出、增益。
- 音质处理：处理前后双波形降噪、目标响度卡、八段均衡器、预设式变速变调。
- 合成与输出：带静音/独奏/音量的轨道时间线、左右声道合成和音轨提取；音乐标签统一在“歌词与标签”维护。

裁剪工作台可拖动或精确输入选区，并选择“提取片段”或“删除片段”；其他工具按自己的
处理逻辑组织参数和试听。默认在原素材旁建立 `Echovault编辑输出`，所有操作
生成新文件，不覆盖原素材。手机任务来源的结果会自动进入“待回传”。

媒体时长与波形在后台读取；未变化的同一文件会复用最近八个素材的波形缓存。隐藏工作台
不会跟随播放头或选区重绘，时间线会缓存刻度与 4,000 点波形静态层，只单独刷新红色播放头
和蓝色选区，长音频播放和拖动时更流畅。
完整说明见 [音频编辑使用指南](docs/音频编辑使用指南.md)。

## 命令行

```powershell
# 环境诊断
python main.py doctor --json

# 列出无歌词素材
python main.py list --status no-lrc --json

# 批量识别目录
python main.py transcribe .\music --language zh --json

# 设置识别引擎和语言
python main.py config set asr.provider local
python main.py config set asr.language zh

# 诊断 GPU
python main.py gpu scan
python main.py gpu status

# 管理素材库与详情页全选范围
python main.py library add E:\\music --mode music
python main.py library select-all on --mode music

# 视频时间校准、导出与汇总
python main.py video calibrate E:\\video --source 2026-07-15T10:00:00 --target 2026-07-15T12:00:00
python main.py video timeline E:\\video

# 内置 AI 助手（使用设置中选中的在线或本地接口）
python main.py ai chat "这个软件如何离线识别？"

# 翻译单份或整个目录的 LRC，原时间戳不变
python main.py lyrics translate E:\music --engine local --source en --target-language zh --json
```

完整参数参见 [CLI.md](CLI.md)。

## 项目结构

```text
Echovault/
├── main.py                  # GUI 与 CLI 入口
├── core/                    # 配置、ASR、音频、LRC、模型、同步与视频逻辑
├── ui/                      # PyQt6 主窗口、素材库、密钥管理、设置与编辑器
├── worker/                  # 独立 CPU/CUDA Whisper Worker
├── services/                # 素材扫描等业务服务
├── server/                  # LocalSend 与 HTTP 服务
├── mcp_server.py            # MCP stdio / Streamable HTTP 接口
├── tests/                   # pytest 回归测试
├── Echovault.spec           # PyInstaller 发布目录配置
├── build.ps1                # Windows 构建脚本
├── requirements-cloud.txt   # Groq 在线模式依赖
├── requirements-translation.txt # Argos 本地离线翻译依赖
└── requirements-local.txt   # 本地 Whisper 依赖
```

## MCP 接口

现有 CLI 白名单可通过 MCP 提供给 AI 客户端。默认只读；写操作需要启动参数与逐次确认两道授权。

```powershell
pip install -r requirements-mcp.txt
python mcp_server.py
```

详细配置与安全边界见 [MCP 接口使用指南](docs/MCP接口使用指南.md)。

## 致谢

- [OpenAI Whisper](https://github.com/openai/whisper)
- [Groq](https://groq.com/)
- [LocalSend](https://github.com/localsend/localsend)
- [OpenCC](https://github.com/BYVoid/OpenCC)

## License

MIT，详见 [LICENSE](LICENSE)。
