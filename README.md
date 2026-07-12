# Echovault / 琳琅乐府

> AI 驱动的歌词识别 + 本地优先的文件同步 | 开源桌面应用

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)](https://riverbankcomputing.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Dev-orange)]()

---

## 概述

**琳琅乐府**是一个桌面端音乐管理工具。它解决两个痛点：

1. **你的本地音乐库有几千首歌，但大部分没有歌词。**  
   琳琅乐府用 AI 自动「听」出歌词，生成标准 LRC 时间轴文件，播放器就能逐行高亮显示了。

2. **你想把手机上的新歌传到电脑统一管理，但不想插数据线。**  
   琳琅乐府实现了 LocalSend 协议，手机 App 直接无线传文件到电脑指定文件夹。

全部代码本地运行。你不用上传歌曲到任何云端服务，隐私安全。

---

## 核心亮点

| 特性 | 说明 |
|------|------|
| 双引擎切换 | Groq 云端 Whisper（免费、极速）+ 本地 OpenAI Whisper（离线零成本） |
| 中文优化 | 繁简自动转换（OpenCC），China-friendly 模型下载（魔搭 / GitHub Releases） |
| 完整 LRC 支持 | 生成、解析、编辑、全局时间偏移、格式转换 |
| 纯音乐检测 | 识别后歌词过短自动标记，批量处理跳过 |
| 多格式 | MP3 / FLAC / WAV / AAC / M4A / OGG / OPUS |
| LocalSend 协议 | 手机 App 直连，无需额外安装任何手机端软件 |
| 灵活同步 | 4 种方向（单向/双向/镜像），文件夹差异可视化 |
| 歌曲管理 | 双筛选器、搜索、双击改名（同步改 LRC）、右键标记 |

---

## 快速开始

```bash
# 克隆
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault

# 安装核心依赖
pip install -r requirements.txt

# 安装引擎（二选一）
pip install groq           # 云端，有免费额度，推荐
pip install openai-whisper  # 本地离线，需下载模型

# 启动
python main.py
```

### 模型下载

本地 Whisper 需要的模型文件托管在独立仓库：

**github.com/xiaohaifale-QWQ/echovault-models/releases**

软件内的下载按钮直接从此仓库拉取，国内 GitHub 可直接访问。

---

## 使用说明

### 图形界面

```
┌─────────────────┬──────────────────────────┐
│   歌曲列表       │   详情 / 音乐库 / 同步    │
│   (筛选/搜索)    │   (歌词预览/文件夹树/传输) │
│   [批量识别]     │                          │
└─────────────────┴──────────────────────────┘
```

### 命令行

```bash
python main.py transcribe ./music/ --language zh --force
```

### 手机同步流程

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
- 内置模型下载器（实时速度、进度百分比、剩余时间）
- 批量识别（自动跳过已有歌词和纯音乐）
- 后处理管道：合并短句 → 拆分长行 → 删除重复 → 繁转简
- 自动纯音乐检测：歌词 < 20 字自动标记

### LRC 编辑器
- 逐行编辑、时间戳可视化
- 全局时间偏移（整首歌前后平移）
- 添加 / 删除歌词行

### 文件同步
- LocalSend v2.1 协议接收端（HTTPS + mDNS）
- 文件夹差异对比（文件名 / 大小 / 时间 / MD5）
- 同步方向：A→B / B→A / 双向合并 / 完全镜像
- 去重（同名同大小跳过）、冲突处理
- HTTP 浏览服务（手机浏览器可下载电脑文件）

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
| 人声分离 | Demucs（可选） | 提升识别准确率 |

---

## 项目结构

```
Echovault/
├── core/
│   ├── asr/              # ASR 引擎层（Provider 模式、自动回退）
│   ├── config.py         # JSON 配置持久化
│   ├── audio_utils.py    # ffmpeg 音频格式转换
│   ├── lrc_parser.py     # LRC 文件解析/格式化
│   ├── lrc_writer.py     # 识别结果→LRC + 后处理管道
│   ├── metadata.py       # mutagen 元数据读写
│   ├── sync_engine.py    # 文件同步引擎（对比/计划/执行）
│   └── whisper_loader.py # HF 格式模型加载器
├── server/
│   ├── localsend_receiver.py  # LocalSend 协议接收端
│   ├── http_server.py     # HTTP 文件浏览
│   └── discovery.py       # mDNS 设备发现
├── ui/
│   ├── main_window.py     # 主窗口（双栏 + 选项卡）
│   ├── library_panel.py   # 文件夹树
│   ├── song_list_panel.py # 歌曲列表
│   ├── detail_panel.py    # 详情 + 歌词预览
│   ├── lyrics_editor.py   # LRC 编辑器
│   ├── settings_dialog.py # 偏好设置
│   ├── sync_panel.py      # 同步面板
│   └── transcribe_worker.py  # QThread 后台识别
├── main.py
└── requirements.txt
```

---

## 开发状态

- [x] AI 歌词识别（云端 + 本地）
- [x] LRC 完整管道（解析/生成/编辑/后处理）
- [x] 批量处理 + 进度条
- [x] 歌曲筛选/搜索/改名（同步改 LRC）
- [x] 纯音乐标记（手动 + 自动检测）
- [x] LocalSend 协议接收端（HTTPS + mDNS）
- [x] 文件夹差异对比 + 多方向同步
- [x] 内置模型下载器（速度/进度/ETA）
- [x] 繁简自动转换
- [x] PyQt6 桌面 GUI
- [ ] 手机端 App
- [ ] 独立 exe/dmg 打包
- [ ] AI 歌词翻译

---

## 致谢

- [OpenAI Whisper](https://github.com/openai/whisper) — 核心语音识别引擎
- [LocalSend](https://github.com/localsend/localsend) — 跨平台文件传输协议
- [LDDC](https://github.com/chenmozhijin/LDDC) — 桌面歌词工具参考
- [Lyrico](https://github.com/Replica0110/Lyrico) — Android 音乐标签编辑器参考

## License

MIT © xiaohaifale
