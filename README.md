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
- 通过 LocalSend 从手机无线收取文件，并进行本地文件夹同步。

## 功能一览

| 模块 | 功能 |
| --- | --- |
| 素材库 | 音乐、视频两种互斥模式；文件夹独立保存；Finder 式多列浏览，双击文件夹向右展开，窄窗口可横向滚动。 |
| 歌词识别 | Groq Whisper 在线识别与本地 Whisper 离线识别；批量任务显示真实已完成数量，单个素材显示当前阶段和等待状态。 |
| 本地模型 | `tiny`、`base`、`small`、`medium` 模型从项目 Release 下载，支持续传、SHA-256 校验、分片合并和临时文件清理。 |
| GPU | 自动诊断显卡与运行时；可安装并启用匹配的外置 GPU 推理运行时，无法使用时安全回退 CPU。 |
| 视频时间 | 读取视频时间元数据；左、右时间可精确编辑到秒；使用小时偏移快速校准并导出视频文字时间轴。 |
| LRC | 生成、繁转简、编辑、时间戳调整、歌词预览与同名 LRC 自动刷新。 |
| 密钥管理 | 顶栏集中管理 Groq、讯飞和 DeepSeek Key；Key 仅保存在当前 Windows 用户的本机配置中。 |
| AI 助手 | 可展开的最左侧聊天栏，默认调用 DeepSeek，并在每次对话中加载内置使用手册与系统提示词。 |
| 同步 | LocalSend 接收端、文件夹差异比较、单向/双向/镜像同步与冲突确认。 |
| CLI | 支持识别、配置、模型、GPU 和环境诊断命令，并提供 JSON 输出。 |

## 隐私与网络

- 使用本地 Whisper 时，音频与模型均在本机处理。
- 使用 Groq 在线识别时，待识别音频会发送给 Groq API；请只对允许上传的素材使用该模式。
- API Key 不写入项目、源码、Git 或日志，保存在 `~/.music-lyrics-sync/config.json`。该文件属于当前 Windows 用户，应妥善保护。
- AI 模式默认调用 DeepSeek；只有手动启动 AI 模式并发送消息时才会发起请求。

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

1. 打开右侧“素材库”。
2. 在“音乐模式”或“视频模式”下点击“添加文件夹”。两种模式的文件夹完全独立。
3. 添加后左列显示已添加的素材根目录，右列立即显示其中内容；双击子文件夹继续向右展开。
4. 选择音频或视频后开始识别。视频会自动抽取音轨，输出仍使用标准 LRC 时间轴。

### 2. 选择识别引擎

打开“设置 → 偏好设置”：

- **云端（Groq ✓）**：Key 已在密钥管理中保存时显示勾选。适合网络可用且希望快速识别的场景。
- **本地**：选择模型并下载；音频不离开电脑。可以在同一页诊断并启用 GPU 运行时。

Groq 连接失败时会区分 Key 无效、调用额度不足和 `api.groq.com:443` 网络/TLS 超时，便于定位原因。

### 3. 管理 API Key

顶栏点击“密钥管理”：

- **Groq API Key**：用于 Groq 在线转写。
- **Groq 代理地址（可选）**：直连无法访问 Groq 时，可填写正在运行的本地 HTTP 代理，例如 `http://127.0.0.1:7890`。
- **讯飞极速录音转写**：在密钥管理中填写同一讯飞应用的 `AppID`、`API Key`、`API Secret`，并在讯飞控制台开通“极速录音转写”。Echovault 会将完整素材转换为 16 kHz 单声道音频后整体上传识别，不会为适配接口而切分歌曲；该服务会将音频上传到讯飞云端。
- **DeepSeek API Key**：用于内置 AI 助手。默认接口为 `https://api.deepseek.com`，默认模型为 `deepseek-chat`，也可在密钥管理中改为其他 OpenAI 兼容接口。

保存后偏好设置不会再次显示 Groq Key 输入框，只显示配置状态。清空某一项并保存即可删除该本机 Key。

### 4. AI 模式

点击顶栏“AI 模式”，在弹出的菜单中选择“启动”。已填写 DeepSeek Key 时，主窗口最左侧会出现聊天栏；再次点击“AI 模式 → 关闭”即可收起。AI 每次请求都会读取内置的 Echovault 使用手册和系统提示词，因此可以介绍软件、解释界面或给出 CLI 操作建议。

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

# 内置 DeepSeek 助手
python main.py ai chat "这个软件如何离线识别？"
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
├── tests/                   # pytest 回归测试
├── Echovault.spec           # PyInstaller 发布目录配置
├── build.ps1                # Windows 构建脚本
├── requirements-cloud.txt   # Groq 在线模式依赖
└── requirements-local.txt   # 本地 Whisper 依赖
```

## 致谢

- [OpenAI Whisper](https://github.com/openai/whisper)
- [Groq](https://groq.com/)
- [LocalSend](https://github.com/localsend/localsend)
- [OpenCC](https://github.com/BYVoid/OpenCC)

## License

MIT，详见 [LICENSE](LICENSE)。
