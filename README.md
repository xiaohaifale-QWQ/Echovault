# MusicSync

AI 歌词识别 + 跨设备文件同步

## 功能

### AI 歌词识别
- 支持 **Groq Whisper API**（云端免费）和 **本地 OpenAI Whisper**（离线）
- 中文为主，支持英语/日语/韩语等多语言
- 自动生成 **LRC 时间轴歌词**，与音频文件同名存放
- 批量处理，后台异步识别，不阻塞界面
- 可视化 **LRC 歌词编辑器**：逐行编辑、时间轴调整、全局偏移
- 可选 **Demucs 人声分离**，提升识别准确率

### 文件同步
- 电脑和手机之间文件夹同步比对
- **4 种同步方向**：单向/双向/完全镜像
- 差异可视化（仅在A/B、更新、冲突）
- **局域网 HTTP 文件服务**：手机浏览器直接访问下载
- **mDNS 设备发现**：自动扫描局域网内的 MusicSync 设备

## 安装

### 环境要求
- Python 3.10+
- ffmpeg（系统安装）

### 安装依赖

```bash
cd music-lyrics-sync
pip install -r requirements.txt
```

### 可选依赖

```bash
# 云端识别（推荐，免费）
pip install groq

# 本地离线识别
pip install openai-whisper

# 人声分离
pip install demucs

# 局域网设备发现
pip install zeroconf
```

## 使用

### 启动 GUI

```bash
python main.py
```

### 命令行模式

```bash
# 识别单首歌
python main.py transcribe /path/to/song.mp3

# 批量识别文件夹（中文）
python main.py transcribe /path/to/music/ --language zh

# 强制覆盖已有歌词
python main.py transcribe /path/to/music/ --force
```

### 首次使用

1. 启动 GUI: `python main.py`
2. 菜单 -> 设置 -> 填入 Groq API Key（[免费获取](https://console.groq.com/keys)）
3. 文件 -> 打开音乐文件夹
4. 点击文件夹加载歌曲
5. 选中歌曲 -> 点击「识别歌词」
6. 或菜单 -> 识别 -> 识别全部未标注歌曲

### 手机同步

1. GUI 切换到「同步」选项卡
2. 配置本机路径（自动填入当前音乐文件夹）
3. 输入手机端文件夹路径
4. 点击「对比」查看差异
5. 点击「启动服务」开启 HTTP 文件服务
6. 手机浏览器访问显示的地址

## 项目结构

```
music-lyrics-sync/
├── main.py                    # 入口（默认启动 GUI）
├── core/                      # 核心引擎
│   ├── asr/                   # ASR 语音识别
│   │   ├── base.py           # Provider 抽象接口
│   │   ├── groq_whisper.py   # Groq 云端
│   │   ├── local_whisper.py  # 本地 Whisper
│   │   └── router.py         # ASR 路由器（自动回退）
│   ├── config.py             # 配置管理
│   ├── audio_utils.py        # 音频转换（ffmpeg）
│   ├── lrc_parser.py         # LRC 解析/格式化
│   ├── lrc_writer.py         # 识别结果 -> LRC
│   ├── metadata.py           # 音频标签读写（mutagen）
│   └── sync_engine.py        # 文件同步引擎
├── server/                    # 同步服务
│   ├── http_server.py        # HTTP 文件传输
│   └── discovery.py          # mDNS 设备发现
├── ui/                        # PyQt6 桌面 GUI
│   ├── main_window.py        # 主窗口
│   ├── library_panel.py      # 音乐库文件夹树
│   ├── song_list_panel.py    # 歌曲列表
│   ├── detail_panel.py       # 详情/歌词预览
│   ├── lyrics_editor.py      # LRC 编辑器
│   ├── settings_dialog.py    # 设置对话框
│   ├── sync_panel.py         # 同步面板
│   └── transcribe_worker.py  # 后台转录线程
└── tests/
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 语音识别 | Groq Whisper API / OpenAI Whisper |
| 人声分离 | Demucs（可选） |
| 音频处理 | ffmpeg + pydub |
| 标签读写 | mutagen |
| GUI | PyQt6 |
| 文件同步 | aiohttp + Zeroconf |

## 参考项目

- [LDDC](https://github.com/chenmozhijin/LDDC) — Python+PySide6 桌面歌词工具
- [Lyrico](https://github.com/Replica0110/Lyrico) — Android 音乐标签编辑器
- [OpenAI Whisper](https://github.com/openai/whisper) — 语音识别引擎
- [Syncthing](https://github.com/syncthing/syncthing) — P2P 文件同步

## License

MIT
