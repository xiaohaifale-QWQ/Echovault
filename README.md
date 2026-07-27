# 琳琅乐府 Echovault

本地优先的音视频素材库、歌词识别、音频编辑与 AI 自动化桌面工具。

[![Windows](https://img.shields.io/badge/Windows-10%2F11-1677ff)](https://github.com/xiaohaifale-QWQ/Echovault/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-22a06b)](LICENSE)

[下载 Windows 开发版](https://github.com/xiaohaifale-QWQ/Echovault/releases/tag/v0.7.0-dev.20260728) · [使用文档](docs/统一工作区界面指南.md) · [问题反馈](https://github.com/xiaohaifale-QWQ/Echovault/issues)

## 它能做什么

| 模块 | 能力 |
| --- | --- |
| 素材库 | 按文件夹管理音乐与视频，多选素材并集中处理 |
| 歌词与标签 | 在线歌词与封面、本地识别、歌词核对、翻译及音频标签写入 |
| 音频工作台 | 波形裁剪、增益、淡入淡出、降噪、响度、均衡器、变速变调与多轨处理 |
| 人声分离 | 分离人声与伴奏，支持 Demucs、UVR 降噪和去混响 |
| 音频下载 | 加载兼容音源脚本，搜索、试听、下载并查看记录 |
| 批量整理 | 按规则匹配封面和歌词、识别、翻译并实时输出执行日志 |
| 导出与传输 | 通过局域网与手机互传文件，或进行高级文件夹同步 |
| AI 助手 | 用自然语言调用素材、识别、编辑、导出与传输操作 |

## 设计原则

- **本地优先**：素材库、编辑结果和模型保存在本机；在线服务只在用户选择时调用。
- **不破坏原文件**：音频处理默认另存为新文件，歌词与标签可由用户决定是否写回。
- **统一播放控制**：全软件同一时间只播放一个音频，切换模块不会叠加播放。
- **适合自动化**：CLI 与 MCP 提供结构化 JSON 结果，危险写入操作需要明确确认。

## 快速开始

### 直接使用

1. 从 [Releases](https://github.com/xiaohaifale-QWQ/Echovault/releases/tag/v0.7.0-dev.20260728) 下载 Windows 压缩包。
2. 完整解压后运行 `Echovault.exe`。
3. 第一次使用本地识别或人声分离时，在“模型库”中下载所需模型。

### 从源码运行

```powershell
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault
python -m pip install -r requirements/cloud.txt
python main.py
```

本地 Whisper、人声分离和离线翻译属于可选能力：

```powershell
python -m pip install -r requirements/local.txt
python -m pip install -r requirements/translation.txt
```

系统需要可用的 `ffmpeg` 与 `ffprobe`。NVIDIA 用户可按 [CLI、模型与 CUDA 指南](docs/AI调用CLI与CUDA使用指南.md) 配置 GPU 加速。

## 给 AI 或脚本调用

Echovault 可以先检查环境，再执行转写或非破坏式音频处理：

```powershell
python main.py doctor --json
python main.py transcribe "D:\资料\访谈.mp4" --provider local --json
python main.py audio process volume "D:\音频\原曲.flac" --param gain_db=3 --json
```

完整接口：

- [CLI 参考手册](docs/CLI.md)
- [MCP 接口使用指南](docs/MCP接口使用指南.md)
- [AI 助手使用手册](docs/AI助手使用手册.md)

## 项目结构

```text
core/          核心领域逻辑
services/      业务服务与外部能力
ui/            PyQt6 桌面界面
worker/        可独立部署的识别运行时
server/        本地传输与服务端组件
docs/          使用与开发文档
requirements/  按场景拆分的依赖清单
packaging/     PyInstaller 打包配置
tools/         构建和维护脚本
tests/         自动化测试
```

## 开发与构建

```powershell
python -m pip install -r requirements/dev.txt
pytest -q
.\tools\build_app.ps1 -Profile Lite
```

`Lite` 版使用在线识别并保持较小体积；`Full` 版同时打包本地 AI 依赖：

```powershell
.\tools\build_app.ps1 -Profile Full -InstallDependencies
```

详细变更见 [CHANGELOG.md](CHANGELOG.md)，历史产品方案见 [开发方案](docs/开发方案.md)。

## 隐私与许可

在线识别会把待处理音频发送给所选服务商；本地识别不会上传媒体。密钥保存在当前 Windows 用户的本地配置中，不写入仓库。

项目采用 [MIT License](LICENSE)。请仅接入并下载你有权使用的音源与内容。
