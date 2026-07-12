# 琳琅乐府 / Echovault

> AI 歌词识别 + 跨设备文件同步 | 开发中

## 简介

琳琅乐府是一款桌面应用，做两件事：

1. **AI 歌词识别** — 用 Whisper 自动听写歌曲，生成 LRC 时间轴歌词
2. **跨设备同步** — 电脑和手机通过 LocalSend 协议互传音乐文件

## 模型下载

Whisper 模型文件托管在独立仓库：**[github.com/xiaohaifale-QWQ/echovault-models](https://github.com/xiaohaifale-QWQ/echovault-models/releases)**

软件内偏好设置 → 本地 Whisper → 下载模型，自动从以上仓库拉取。

## 功能

### AI 歌词识别
- Groq Whisper API（云端免费）+ 本地 OpenAI Whisper（离线）
- 中文为主，支持英语/日语/韩语
- LRC 时间轴歌词自动生成
- 批量识别 + 进度条
- LRC 歌词编辑器（逐行编辑、时间偏移、合并拆分）
- Demucs 人声分离（可选）
- 繁简自动转换（OpenCC）
- 纯音乐自动检测

### 歌曲管理
- MP3/FLAC/WAV/AAC/M4A/OGG 全格式
- 双筛选器：歌词状态 + 文件格式
- 搜索、双击改名（同步重命名 LRC）
- 右键标记纯音乐

### 文件同步
- LocalSend Protocol v2.1 接收端（HTTPS + mDNS）
- 文件夹对比 + 差异可视化
- 手机浏览器 HTTP 下载

### 模型下载
- 从 GitHub Releases 拉取，国内可访问
- 缓存检测，避免重复下载
- 实时速度 + 剩余时间进度条
- tiny / base / small / medium 四档

## 安装

```bash
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault
pip install -r requirements.txt
```

可选：
```bash
pip install groq              # 云端识别（免费）
pip install openai-whisper     # 本地离线
pip install demucs             # 人声分离
```

## 使用

```bash
python main.py                 # 启动 GUI
python main.py transcribe ./   # 命令行批量识别
```

首次使用：设置 → 填入 Groq API Key，或切到本地 Whisper → 下载模型。

## 手机同步
1. 切到同步选项卡
2. 点「开启 LocalSend 接收」
3. 手机打开 LocalSend App，找 MusicSync 设备，发文件

## 项目结构

```
core/           # 核心引擎
├── asr/        # ASR 语音识别（Groq + 本地）
├── config.py   # 配置管理
├── audio_utils.py  # ffmpeg 音频处理
├── lrc_parser.py   # LRC 解析
├── lrc_writer.py   # 识别结果 → LRC
├── metadata.py     # mutagen 标签读写
├── sync_engine.py  # 同步引擎
└── whisper_loader.py # HF 模型加载器

server/         # 同步服务
├── localsend_receiver.py  # LocalSend 接收端
└── http_server.py         # HTTP 浏览

ui/             # PyQt6 GUI
├── main_window.py     # 主窗口
├── library_panel.py   # 音乐库
├── song_list_panel.py # 歌曲列表
├── detail_panel.py    # 详情 + 歌词预览
├── lyrics_editor.py   # LRC 编辑器
├── settings_dialog.py # 偏好设置
└── sync_panel.py      # 同步面板
```

## 技术栈

| 层 | 技术 |
|------|------|
| 语音识别 | Groq Whisper API / OpenAI Whisper |
| 音频 | ffmpeg + pydub |
| 标签 | mutagen |
| GUI | PyQt6 |
| 同步 | LocalSend Protocol v2.1 |

## 开发进度

- [x] AI 歌词识别（云端 + 本地）
- [x] LRC 解析/生成/编辑
- [x] 批量识别 + 进度条
- [x] 歌曲筛选、搜索、改名
- [x] 纯音乐标记
- [x] LocalSend 接收端 (HTTPS)
- [x] 文件夹对比同步
- [x] 模型下载器
- [x] PyQt6 GUI
- [ ] 手机端 App
- [ ] exe 打包
- [ ] AI 歌词翻译

## 参考

- [OpenAI Whisper](https://github.com/openai/whisper)
- [LocalSend](https://github.com/localsend/localsend)
- [LDDC](https://github.com/chenmozhijin/LDDC)

## License

MIT
