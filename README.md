# Echovault / 琳琅乐府

> AI 驱动的歌词识别 + LocalSend 跨设备文件同步 | 开发中

## 这是什么

琳琅乐府是一款桌面应用，围绕音乐文件做两件核心事：

### 1. AI 歌词识别

输入一首歌的音频文件（MP3/FLAC/WAV 等），AI 自动听写出歌词，生成带时间戳的 **LRC 歌词文件**。原理是用 OpenAI 的 Whisper 模型将语音转为文字，再经后处理生成标准 LRC 格式。

支持两种识别引擎：
- **Groq Whisper**（云端，免费额度，速度快）
- **本地 Whisper**（离线，需下载模型文件，数据不出电脑）

### 2. 跨设备文件同步

实现了 **LocalSend v2.1 协议**的接收端。电脑开启服务后，手机上的 LocalSend App 可以直接发现本机，把音乐文件发过来，自动保存到指定文件夹。支持文件夹差异对比、去重、进度显示。

## 下载和安装

### 环境要求
- Python 3.10 或更高
- [ffmpeg](https://ffmpeg.org)（系统安装，用于音频格式转换）

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault

# 安装依赖
pip install -r requirements.txt
```

### 引擎配置

**云端识别（推荐，有免费额度）：**
```bash
pip install groq
```
然后在设置里填 Groq API Key（免费获取：https://console.groq.com/keys）

**本地离线识别：**
```bash
pip install openai-whisper
```
然后在设置里切到「本地 Whisper」→「下载模型」。模型从配套仓库自动拉取，国内可访问。

模型文件托管在独立仓库：`github.com/xiaohaifale-QWQ/echovault-models`

### 可选功能

```bash
pip install demucs        # 人声分离（识别前把伴奏和人声分开，提升准确率）
pip install cryptography  # LocalSend HTTPS 支持
```

## 使用方法

### 图形界面

```bash
python main.py
```

窗口布局：
- 左侧：歌曲列表（筛选、搜索、改名）
- 右侧选项卡：详情（歌词预览）/ 音乐库（文件夹树）/ 同步

### 命令行

```bash
# 识别单首歌
python main.py transcribe /path/to/song.mp3

# 批量识别整个文件夹（中文歌曲）
python main.py transcribe /path/to/music/ --language zh

# 强制覆盖已有歌词
python main.py transcribe /path/to/music/ --force
```

### 首次使用流程

1. `python main.py` 启动
2. 菜单 → 设置 → 选择识别引擎（Groq 云端 / 本地 Whisper）
3. 如果选本地，点「下载模型」等待完成
4. 文件 → 打开音乐文件夹
5. 歌曲列表出现，默认筛选「无歌词」
6. 点「批量识别」或选中单首点「识别歌词」
7. 识别完成后右侧自动显示歌词预览

### 手机同步

1. 切换到「同步」选项卡
2. 配置本机文件夹路径
3. 点击「开启 LocalSend 接收」
4. 手机打开 LocalSend App，查找 **MusicSync** 设备
5. 选择文件发送，自动保存到电脑

## 功能详解

### 歌曲列表

| 功能 | 说明 |
|------|------|
| 筛选器 | 歌词状态（全部/有歌词/无歌词/纯音乐）+ 文件格式 |
| 搜索 | 按歌曲名实时过滤 |
| 改名 | 双击歌曲名弹出对话框，自动同步重命名 LRC 文件 |
| 纯音乐标记 | 右键标记/取消，标记后批量识别自动跳过 |
| 进度条 | 状态栏实时显示识别进度 |

### 歌词识别

| 功能 | 说明 |
|------|------|
| 引擎切换 | Groq 云端 / 本地 Whisper，偏好设置里切换 |
| 模型下载 | 内置下载器，实时显示速度、百分比、剩余时间 |
| 批量识别 | 一键处理所有无歌词歌曲 |
| 后处理 | 合并短句、拆分长行、删除重复 |
| 繁简转换 | 中文歌词自动繁体转简体（OpenCC） |
| 纯音乐检测 | 识别结果过短自动标记为纯音乐 |
| 进度条 | 状态栏显示 N/M 首，带进度条 |

### 歌词编辑器

双击歌曲或点「编辑歌词」打开：
- 逐行编辑歌词文本
- 时间轴可视化
- 全局偏移（前后移动所有行的时间）
- 添加/删除行

### 文件同步

| 功能 | 说明 |
|------|------|
| LocalSend 接收 | 局域网内手机直接传文件 |
| 文件夹对比 | 对比电脑和手机路径的差异 |
| 同步方向 | 单向/双向/完全镜像（手机→电脑、电脑→手机、双向合并） |
| 去重 | 同名同大小文件自动跳过 |
| 进度显示 | 每文件传输进度和速度 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 语音识别 | OpenAI Whisper (本地) / Groq Whisper API (云端) |
| 模型加载 | PyTorch（兼容 HF 格式模型文件） |
| 音频处理 | ffmpeg（转码）+ pydub |
| 标签读写 | mutagen（MP3/FLAC/M4A/OGG） |
| 繁简转换 | OpenCC |
| 桌面界面 | PyQt6 |
| 文件传输 | LocalSend Protocol v2.1 (HTTPS + mDNS) |
| 设备发现 | Zeroconf / Bonjour |
| 人声分离 | Demucs（可选） |

## 项目结构

```
Echovault/
├── main.py                # 入口（支持 GUI 和命令行）
├── core/
│   ├── asr/               # ASR 引擎
│   │   ├── base.py       # Provider 抽象接口
│   │   ├── groq_whisper.py  # Groq 云端
│   │   ├── local_whisper.py # 本地 Whisper
│   │   └── router.py     # 路由器（自动回退）
│   ├── config.py          # 配置管理（JSON 持久化）
│   ├── audio_utils.py     # 音频转换（ffmpeg）
│   ├── lrc_parser.py      # LRC 解析/格式化
│   ├── lrc_writer.py      # 识别结果 → LRC + 后处理
│   ├── metadata.py        # 音频标签读写（mutagen）
│   ├── sync_engine.py     # 文件同步引擎
│   └── whisper_loader.py  # HF 格式模型加载器
├── server/
│   ├── localsend_receiver.py  # LocalSend 接收端 (HTTPS)
│   ├── http_server.py     # HTTP 浏览服务
│   └── discovery.py       # mDNS 设备发现
├── ui/
│   ├── main_window.py     # 主窗口框架
│   ├── library_panel.py   # 音乐库文件夹树
│   ├── song_list_panel.py # 歌曲列表（筛选/搜索/改名）
│   ├── detail_panel.py    # 详情 + 歌词预览
│   ├── lyrics_editor.py   # LRC 可视化编辑器
│   ├── settings_dialog.py # 偏好设置（含模型下载）
│   ├── sync_panel.py      # 同步面板
│   └── transcribe_worker.py  # 后台识别线程
└── tests/
```

## 开发进度

- [x] AI 歌词识别（Groq 云端 + 本地 Whisper）
- [x] LRC 时间轴歌词生成 + 后处理
- [x] 批量识别 + 进度条
- [x] LRC 可视化编辑器
- [x] 歌曲筛选（状态 / 格式）、搜索、改名
- [x] 纯音乐标记（手动 + 自动检测）
- [x] LocalSend Protocol v2.1 接收端（HTTPS + mDNS）
- [x] 文件夹对比 + 多种同步方向
- [x] 模型下载器（速度 + 进度 + ETA）
- [x] 繁简自动转换（OpenCC）
- [x] PyQt6 完整 GUI
- [ ] 手机端 App
- [ ] 打包为独立 exe / dmg
- [ ] AI 歌词翻译
- [ ] 音乐指纹识别

## 参考项目

- [OpenAI Whisper](https://github.com/openai/whisper) — 语音识别引擎
- [LocalSend](https://github.com/localsend/localsend) — 跨平台文件传输协议
- [LDDC](https://github.com/chenmozhijin/LDDC) — Python+PySide6 桌面歌词工具
- [Lyrico](https://github.com/Replica0110/Lyrico) — Android 音乐标签编辑器

## License

MIT
