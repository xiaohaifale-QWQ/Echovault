# Echovault 给 AI 的 CLI、模型与 CUDA 使用指南

本文供 Codex、Claude、Cursor、OpenAI 兼容 Agent 和 Echovault 内置 AI 使用。目标是让 AI 直接调用 Echovault 完成“视频抽取音轨 → 语音识别 → LRC/时间轴整理”，而不是各自重复搭建 FFmpeg、Whisper 和 CUDA 环境。

## 1. 入口与约定

源码开发版在项目目录执行：

```powershell
python main.py <命令> [参数]
```

打包版直接把 `Echovault.exe` 当作 CLI：

```powershell
Echovault.exe <命令> [参数]
```

面向程序调用时优先加 `--json`。结构化结果写到标准输出，下载和处理进度写到标准错误；成功退出码为 `0`，失败为非零。路径含空格时必须整体加双引号。

不要通过 shell 拼接命令，不要使用管道、重定向或 `shell=True`。每次只执行一个命令并检查退出码及 JSON，再决定下一步。

## 2. 首次安装：诊断、模型与 CUDA

先诊断本机：

```powershell
python main.py doctor --json
python main.py gpu scan --json
python main.py model list --json
```

本地识别至少需要一个 Whisper 模型。`base` 是默认平衡选择：

```powershell
python main.py model download base --json
python main.py config set asr.provider local
python main.py config set asr.local_model base
```

模型保存在当前用户的 `~/.cache/whisper`，下载支持断点续传并校验 SHA-256。可选模型：

| 模型 | 典型用途 | 大小 |
| --- | --- | --- |
| `tiny` | 快速预览、低配置电脑 | 约 144 MB |
| `base` | 日常识别，推荐 | 约 139 MB |
| `small` | 多语言和更高准确度 | 约 922 MB |
| `medium` | 高准确度、显存和耗时更高 | 约 2.9 GB |

NVIDIA 显卡使用一键运行时配置：

```powershell
python main.py gpu setup --json
python main.py gpu status --json
```

`gpu setup` 会检测显卡、驱动和计算能力，选择兼容的 CUDA 运行时，读取签名发布清单，下载、校验、试运行后再原子激活。它不会修改系统 CUDA，也不要求用户手工安装 PyTorch。无兼容 GPU 时自动保持 CPU。检测成功后会同步启用本地 ASR 和人声分离的 GPU 开关。

注意：

- CUDA 是否可用取决于 NVIDIA 驱动版本和显卡计算能力，不是仅看“安装了 CUDA”。
- 不要让 AI 随意执行 `pip install torch` 覆盖软件运行时。
- 如果 `gpu scan` 推荐 CPU，先升级官方显卡驱动，再重新扫描。
- AMD/Intel 当前会回退 CPU；WinML Worker 发布前不应强行启用。

## 3. 视频和音频识别

`transcribe` 直接接受音频、视频或包含二者的目录。视频由内置 FFmpeg 临时抽取为 16 kHz 单声道音频，然后进入同一识别管线；临时文件会清理。

```powershell
python main.py transcribe "D:\资料\访谈.mp4" --provider local --language zh --json
python main.py transcribe "D:\资料" --provider local --json
```

也可以使用更直观的视频别名：

```powershell
python main.py video transcribe "D:\资料\访谈.mp4" --provider local --json
```

默认在媒体旁生成同名 `.lrc`；使用 `--output-dir` 可集中输出。已有 LRC 默认跳过，加 `--force` 才覆盖。AI 不得擅自添加 `--force`。

只有下游工具确实需要独立 WAV 时才抽取音轨：

```powershell
python main.py video extract-audio "D:\资料\访谈.mp4" `
  --output "D:\资料\访谈.asr.wav" --json
```

输出固定为 16 kHz、单声道 WAV，适合 ASR，不适合作为高保真音乐导出。

## 4. 音频编辑与人声分离

音频编辑统一使用非破坏式接口，输出路径不能等于任一输入路径：

```powershell
python main.py audio process trim `
  --input "D:\音乐\原曲.flac" `
  --output "D:\音乐\原曲_片段.flac" `
  --param start=10 --param end=35 --json

python main.py audio process volume `
  --input "D:\音乐\原曲.flac" `
  --output "D:\音乐\原曲_增益.flac" `
  --param gain_db=3 --param prevent_clipping=true --json
```

操作名包括：

`extract`、`trim`、`edit`、`concat`、`mix`、`fade`、`speed_pitch`、`denoise`、`normalize`、`split`、`equalizer`、`volume`、`tags`、`reverse`、`convert`。

拼接和混音可重复传入 `--input`。普通参数优先重复使用 `--param 键=值`，值会自动解析为数字、布尔值或字符串；数组等复杂值可用 `--params-json` 传递。直接从 PowerShell 调用时，`--param` 可避免原生程序参数对 JSON 双引号的二次处理。

人声分离：

```powershell
python main.py audio separate "D:\音乐\原曲.flac" `
  --output-dir "D:\音乐\分离结果" `
  --model htdemucs --device auto --output-content both --json
```

可选 `--denoise` 和 `--dereverb`。模型必须先在软件“模型库”安装；`auto` 会优先使用已验证的 CUDA Worker。

## 5. 歌词、音源与素材库

常用只读操作：

```powershell
python main.py lyrics show "D:\音乐\歌曲.flac" --json
python main.py lyrics online-search "歌名" --artist "歌手" --json
python main.py library list --mode music --json
python main.py download search "歌名 歌手" --source "音源ID" --json
```

写操作：

```powershell
python main.py lyrics translate "D:\音乐\歌曲.lrc" --target-language zh --json
python main.py download fetch "歌名 歌手" --source "音源ID" --index 0 `
  --quality 128k --output-dir "D:\下载" --json
```

音频下载只使用用户已在“设置 → 音源管理”导入并启用的授权音源。AI 不得自行添加未知音源、绕过版权或下载用户没有权利获取的内容。

## 6. 内置 AI 的自然语言控制

内置 AI 只收到当前选中素材的文件名，不上传本机完整路径。用户说“识别当前视频”“把当前歌曲音量提高 3 dB”时，AI 应在指令里使用：

- `@current`：当前文件；
- `@current-dir`：当前文件所在目录。

示例回答：

```text
我会用当前本地识别引擎生成同名 LRC；已有歌词时默认跳过。
[[ECHOVAULT_CLI: transcribe @current --provider local --json]]
```

系统在执行前将占位符解析为当前绝对路径。读取类命令直接执行；识别、下载、编辑、模型/CUDA 安装、配置和文件修改必须弹出确认。一次回答最多一个命令，多步任务要等待上一步结果。

如果用户只是要求“打开歌词核对”“进入人声分离”“打开音源设置”，AI 使用当前窗口导航指令：

```text
[[ECHOVAULT_UI: open lyrics-review]]
[[ECHOVAULT_UI: open audio-separate]]
[[ECHOVAULT_UI: open settings-audio-sources]]
```

UI 目标采用固定白名单，不接受任意 Python 方法名。导航指令不会启动另一个软件进程。界面导航和文件 CLI 不应在同一回答中同时发出。

内置 AI 和 MCP 共用同一白名单，拒绝 PowerShell、cmd、脚本、分号、管道、重定向、反引号和美元符号。

## 7. 外部 AI：MCP

安装并启动：

```powershell
python -m pip install -r requirements-mcp.txt
python mcp_server.py
```

默认只读。允许写操作必须由用户显式启动：

```powershell
python mcp_server.py --allow-writes
```

随后每一个写调用仍要传 `confirmed=true`，形成“服务器授权 + 单次确认”两道门。AI 应先调用 `echovault_capabilities` 获取当前命令范围，再调用 `echovault_execute`。完整配置见《MCP接口使用指南》。

## 8. 推荐给资料整理 AI 的工作流

1. `doctor --json` 检查 FFmpeg、Provider、模型和运行时。
2. `info` 或素材库命令确认输入文件。
3. 对视频直接执行 `transcribe`，不要预先永久拆音频。
4. 检查 `summary.failed` 和每个 `results[].status`。
5. 读取生成的 LRC；需要跨视频时间关系时再执行 `video timeline`。
6. 仅在用户明确要求时翻译、覆盖歌词、编辑音频或清缓存。
7. 保留原媒体；音频编辑结果必须写新文件。
