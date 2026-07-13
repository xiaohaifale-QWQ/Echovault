# Echovault / 琳琅乐府

> AI 驱动的歌词识别 + 本地优先的文件同步 | 开源桌面应用

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)](https://riverbankcomputing.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-V0.3--dev-orange)]()

---

## 概述

**琳琅乐府**是一个桌面端音乐管理工具。它解决三个痛点：

1. **你的本地音乐库有几千首歌，但大部分没有歌词。**
   琳琅乐府用 AI 自动「听」出歌词，生成标准 LRC 时间轴文件。

2. **你想把手机上的新歌传到电脑统一管理，但不想插数据线。**
   琳琅乐府实现了 LocalSend 协议，手机 App 直接无线传文件到电脑。

3. **你需要管理和编辑已有歌词。**
   可视化 LRC 编辑器 + CLI 命令行 + JSON 输出，人和 AI 都能用。

程序和音乐库管理均在本机运行。使用 **Groq 云端模式**时，转码后的音频会发送到 Groq API；使用**本地 Whisper 模式**时，音频不会离开本机。

---

## 核心亮点

| 特性 | 说明 |
|------|------|
| 双引擎切换 | Groq 云端 Whisper（免费、极速）+ 本地 OpenAI Whisper（离线） |
| 中文优化 | OpenCC 繁体转简体、可选择识别语言 |
| 完整 LRC 支持 | 生成、解析、编辑、全局时间偏移、格式转换 |
| 纯音乐检测 | 识别后歌词过短自动标记，批量处理跳过 |
| 多格式 | MP3 / FLAC / WAV / AAC / M4A / OGG / OPUS |
| LocalSend 协议 | 使用官方 LocalSend 手机 App 向电脑无线发送文件 |
| GPU 加速 | 本地 Whisper 可选择 CPU/CUDA，CUDA 依赖需单独安装 |
| CLI | 12 个命令、JSON 输出、环境诊断，便于脚本和 AI 调用 |
| 灵活同步 | 4 种方向（单向/双向/镜像），文件夹差异可视化 |
| 歌曲管理 | 双筛选器、搜索、双击改名（同步改 LRC）、右键标记 |

---

## 快速开始

```bash
# 克隆
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault

# 建议创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装基础依赖和云端识别（推荐先打通此路径）
pip install -r requirements-cloud.txt

# 或安装本地 Whisper（体积较大）
pip install -r requirements-local.txt

# ffmpeg 是系统程序，需另外安装并加入 PATH
# Windows 可使用：winget install Gyan.FFmpeg

# 检查环境
python main.py doctor

# 启动 GUI
python main.py

# 或 CLI
python main.py --help
```

### 模型下载

本地 Whisper 模型直接从独立的 GitHub Release 下载：

**https://github.com/xiaohaifale-QWQ/echovault-models/releases/tag/v1.0**

软件会使用 `.download` 临时文件断点续传，并按 Release 资产清单校验文件大小和 SHA-256；校验失败的损坏文件会删除。目前 `tiny`、`base`、`small` 可下载，`medium` 因 Release 缺少 `medium.part2` 会在下载前停止，避免浪费磁盘空间。

---

## 使用说明

### 图形界面

```
+-------------------+--------------------------+
|   歌曲列表         |   详情 / 音乐库 / 同步    |
|   (筛选/搜索)      |   (歌词预览/文件夹树/传输) |
|   [批量识别]       |                          |
+-------------------+--------------------------+
```

### 命令行 (AI Agent 友好)

```bash
# 列出无歌词的歌曲
python main.py list --status no-lrc --json

# 批量识别
python main.py transcribe ./music/ --language zh --json

# 搜索歌词
python main.py lyrics search "理想" --folder ./music/

# 管理配置
python main.py config set asr.provider local
python main.py config set asr.language zh

# GPU 管理
python main.py gpu scan
python main.py gpu status

# 环境诊断
python main.py doctor --json
```

完整 CLI 文档: `CLI.md`

### 手机同步

1. 切到「同步」选项卡 → 点「开启 LocalSend 接收」
2. 手机 LocalSend App 发现「MusicSync」设备
3. 发文件 → 自动保存到电脑

---

## 功能清单

### 歌曲管理
- 歌词状态筛选（全部 / 有歌词 / 无歌词 / 纯音乐）
- 文件格式筛选（动态列出当前文件夹内所有格式）
- 实时搜索
- 双击改名（自动同步重命名 LRC 文件）
- 右键标记纯音乐（存储到 `.musicsync_instrumental.json`）

### AI 识别
- 引擎切换：Groq 云端 ↔ 本地 Whisper
- 内置模型下载器（断点续传、SHA-256 校验、取消按钮）
- 批量识别（自动跳过已有歌词和纯音乐）
- 长音频自动切片并合并时间轴
- 单首识别阶段式进度条（转换→识别→后处理）
- 停止识别按钮
- 后处理管道：合并短句 → 拆分长行 → 删除重复 → 繁转简
- 歌词过短时标记为疑似纯音乐，可人工取消
- 识别完成自动刷新右侧歌词预览

### LRC 编辑器
- 逐行编辑、时间戳可视化
- 全局时间偏移（-30s ~ +30s）
- 添加 / 删除歌词行

### GPU 加速
- Windows 目录版内置 CPU Whisper 运行时，可直接离线识别
- 扫描显卡 → 显示型号
- 源码环境可选安装 PyTorch CUDA（大型依赖，建议在虚拟环境中操作）
- CUDA 不可用时明确回退 CPU

### 文件同步
- LocalSend v2.1 协议接收端（HTTPS + mDNS）
- 文件夹差异对比（路径 / 大小 / 时间 / 可选内容哈希）
- 同步方向：A→B / B→A / 双向合并 / 完全镜像
- 冲突默认不覆盖，镜像删除执行前二次确认
- HTTP 下载限制在音乐库内部，LocalSend 上传采用流式写入

### CLI（命令行接口）
- 12 个命令覆盖主要 GUI 操作和环境诊断
- 主要查询与批处理命令支持 `--json` 输出
- 完整文档: `CLI.md`

---

## 技术栈

| 层 | 技术 | 说明 |
|------|------|------|
| 语音识别 | OpenAI Whisper / Groq Whisper API | 双引擎可切换 |
| 模型加载 | PyTorch | 兼容 HF 和原始格式 |
| 音频处理 | ffmpeg + pydub | 万能格式转码 |
| 标签读写 | mutagen | MP3/FLAC/M4A/OGG |
| GUI | PyQt6 | 跨平台桌面界面 |
| 同步 | LocalSend Protocol v2.1 | HTTPS + TLS 1.3 |
| 繁转简 | OpenCC | 中文后处理 |
| 测试/打包 | pytest / PyInstaller | 自动化回归与 Windows 目录版构建 |

---

## 项目结构

```
Echovault/
├── main.py                 # 入口 (GUI + CLI 12 命令)
├── CLI.md                  # CLI 完整参考手册
├── core/
│   ├── asr/               # ASR 引擎层
│   ├── config.py          # JSON 配置持久化
│   ├── audio_utils.py     # ffmpeg 音频转换
│   ├── lrc_parser.py      # LRC 解析/格式化
│   ├── lrc_writer.py      # 识别->LRC + 后处理
│   ├── metadata.py        # mutagen 元数据
│   ├── sync_engine.py     # 同步引擎
│   ├── model_download.py  # GitHub Release 模型下载器
│   └── whisper_loader.py  # HF 模型加载器
├── services/
│   └── library_service.py # GUI/CLI 共用音乐库业务逻辑
├── server/
│   ├── localsend_receiver.py  # LocalSend 接收端
│   ├── http_server.py     # HTTP 文件浏览
│   └── discovery.py       # mDNS 发现
├── ui/
│   ├── main_window.py     # 主窗口
│   ├── library_panel.py   # 文件夹树
│   ├── song_list_panel.py # 歌曲列表
│   ├── detail_panel.py    # 详情/歌词预览
│   ├── lyrics_editor.py   # LRC 编辑器
│   ├── settings_dialog.py # 偏好设置
│   ├── sync_panel.py      # 同步面板
│   └── transcribe_worker.py  # QThread 后台识别
├── tests/                  # pytest 自动化测试
├── Echovault.spec          # Windows 云端 + 本地 CPU 打包配置
├── build.ps1               # 可复现构建脚本
├── requirements.txt        # 基础依赖
├── requirements-cloud.txt  # Groq 云端模式
└── requirements-local.txt  # 本地 Whisper 模式
```

---

## 开发状态

- [x] Groq 云端歌词识别管线
- [x] LRC 完整管道（解析/生成/编辑/后处理）
- [x] 批量处理 + 阶段式进度条
- [x] 歌曲筛选/搜索/改名
- [x] 纯音乐标记
- [x] LocalSend 接收端
- [x] 文件夹差异对比 + 多方向同步
- [x] 模型断点下载与哈希校验
- [x] 本地 Whisper CPU/GPU 设备选择
- [x] CLI（12 命令 + JSON + doctor）
- [x] 停止识别 + 取消下载按钮
- [x] pytest 核心回归测试
- [x] Windows PyInstaller 构建配置和 CI
- [x] GitHub Release 模型下载、续传与资产校验
- [ ] 补齐 medium 模型的第二个 Release 分片
- [ ] GPU CUDA 独立安装包
- [ ] macOS 打包
- [ ] AI 歌词翻译

---

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| medium 模型不完整 | 进行中 | Release v1.0 缺少 `medium.part2`，软件会阻止无效下载 |
| CUDA 依赖体积大 | 已知限制 | Windows 包内置 CPU 推理；CUDA 仍需在源码环境单独安装 |
| Groq 会上传音频 | 设计行为 | 对隐私敏感的用户应选择本地 Whisper |
| Windows 打包 | 待实机验收 | 已提供 spec、构建脚本和 CI，需在干净机器验证 |

## 致谢

- [OpenAI Whisper](https://github.com/openai/whisper) — 核心语音识别引擎
- [LocalSend](https://github.com/localsend/localsend) — 跨平台文件传输协议
- [LDDC](https://github.com/chenmozhijin/LDDC) — 桌面歌词工具参考
- [Lyrico](https://github.com/Replica0110/Lyrico) — Android 音乐标签编辑器参考

## License

MIT，详见 [LICENSE](LICENSE)。
