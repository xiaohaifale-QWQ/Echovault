# 琳琅乐府 (Echovault) CLI 参考手册

> 面向 AI Agent 和命令行用户的完整操作指南
>
> 版本: 0.2.0 | 更新: 2026-07-13

---

## 一、概述

琳琅乐府提供完整的 CLI（命令行接口），覆盖 GUI 所有操作。每个命令支持 `--json` 输出结构化数据，方便 AI 解析。

### 基本用法

```bash
cd E:\music\music-lyrics-sync
python main.py <命令> [参数] [--json]
```

无参数时启动 GUI。

### 全局约定

| 约定 | 说明 |
|------|------|
| `--json` | 输出 JSON 格式，AI 可直接解析 |
| 退出码 | 成功=0，失败=1 |
| 文件路径 | 支持绝对路径和相对路径 |

---

## 二、命令清单

| 命令 | 用途 | GUI 对应 |
|------|------|---------|
| `list` | 列出歌曲 | 歌曲列表面板 |
| `info` | 歌曲详情 | 详情面板 |
| `transcribe` | 识别歌词 | 识别按钮 |
| `lyrics show` | 显示歌词 | 歌词预览 |
| `lyrics search` | 搜索歌词 | — (新增) |
| `config show` | 查看配置 | 设置对话框 |
| `config set` | 修改配置 | 设置对话框 |
| `config path` | 配置文件路径 | — |
| `model list` | 列出模型 | 模型下拉框 |
| `model info` | 模型详情 | 模型下拉框 |
| `model download` | 下载模型 | 下载模型按钮 |
| `gpu scan` | 扫描显卡 | 扫描显卡按钮 |
| `gpu status` | GPU 状态 | 状态栏引擎显示 |
| `sync compare` | 对比文件夹 | 对比按钮 |
| `sync serve` | HTTP 文件服务 | — |
| `rename` | 重命名歌曲 | 双击改名 |
| `mark` | 标记纯音乐 | 右键标记 |
| `serve http` | HTTP 文件浏览 | — |
| `doctor` | 检查 ffmpeg、依赖、Provider 与模型 | 启动状态提示 |
| `gui` | 启动 GUI | — |

---

## 三、命令详解

### 3.1 `list` — 列出歌曲

扫描文件夹，列出所有音频文件及其歌词状态。

```bash
python main.py list [folder] [--status STATUS] [--format FMT] [--search KW] [--json]
```

| 参数 | 说明 |
|------|------|
| `folder` | 文件夹路径（可选，默认使用配置中的音乐目录） |
| `--status` | 筛选: `all`(全部) / `has-lrc`(有歌词) / `no-lrc`(无歌词) / `instrumental`(纯音乐) |
| `--format` | 按格式筛选: `mp3`, `flac`, `wav`, `m4a` 等 |
| `--search` | 按文件名搜索（模糊匹配） |
| `--json` | JSON 输出 |

**示例:**
```bash
# 列出所有无歌词的歌曲
python main.py list --status no-lrc

# 搜索包含"赵雷"的歌曲
python main.py list --search "赵雷"

# JSON 输出（AI 使用）
python main.py list --status no-lrc --json
```

**JSON 输出格式:**
```json
[
  {
    "name": "song.mp3",
    "path": "E:/music/song.mp3",
    "size": 4294061,
    "size_human": "4.1 MB",
    "has_lrc": false,
    "folder": "subdir"
  }
]
```

---

### 3.2 `info` — 歌曲详情

查看单首歌曲的详细信息。

```bash
python main.py info <file> [--json]
```

| 参数 | 说明 |
|------|------|
| `file` | 音频文件路径（必填） |

**JSON 输出包含:** name, path, size, format, has_lrc, lrc_path, title, artist, album（元数据标签）

---

### 3.3 `transcribe` — 识别歌词

对音频文件进行 AI 语音识别，生成 LRC 时间轴歌词。

```bash
python main.py transcribe <target> [--language LANG] [--force] [--output-dir DIR] [--provider PROV] [--json] [--quiet]
```

| 参数 | 说明 |
|------|------|
| `target` | 音频文件或文件夹路径（必填） |
| `--language`, `-l` | 语言: `zh`(中文) / `en`(英语) / `ja`(日语) / `ko`(韩语) / 不指定=自动检测 |
| `--force`, `-f` | 强制覆盖已有 LRC 文件 |
| `--output-dir`, `-o` | LRC 输出目录（默认与音频同目录） |
| `--provider`, `-p` | 指定 Provider: `groq` / `local`（默认使用配置值） |
| `--json` | JSON 输出结果 |
| `--quiet`, `-q` | 静默模式（只输出最终结果） |

**示例:**
```bash
# 识别单首歌
python main.py transcribe "E:/music/song.mp3" --language zh

# 批量识别整个文件夹，强制覆盖
python main.py transcribe "E:/music/" --language zh --force

# JSON 输出 + 静默模式（AI 用）
python main.py transcribe "E:/music/" --json --quiet
```

**JSON 输出格式:**
```json
{
  "summary": {"total": 10, "ok": 8, "failed": 1, "skipped": 1},
  "results": [
    {"file": "song1.mp3", "status": "ok", "lrc_path": "E:/music/song1.lrc"},
    {"file": "song2.mp3", "status": "failed", "error": "Provider not available"}
  ]
}
```

**退出码:** 有失败时返回 1，全部成功返回 0。

---

### 3.4 `lyrics` — 歌词操作

#### 3.4.1 `lyrics show` — 显示歌词

```bash
python main.py lyrics show <file> [--json]
```

输出 LRC 时间轴歌词内容。

**JSON 输出格式:**
```json
[
  {"ts": 12.34, "text": "第一句歌词"},
  {"ts": 15.67, "text": "第二句歌词"}
]
```

#### 3.4.2 `lyrics search` — 搜索歌词

```bash
python main.py lyrics search <keyword> [--folder DIR] [--json]
```

在所有 LRC 文件中搜索关键词，返回匹配的歌词行。

**示例:**
```bash
python main.py lyrics search "理想" --folder "E:/music/"
```

---

### 3.5 `config` — 配置管理

#### 3.5.1 `config show` — 查看配置

```bash
python main.py config show [--json]
```

输出当前所有配置项。

#### 3.5.2 `config set` — 修改配置

```bash
python main.py config set <key> <value>
```

| 配置键 | 可选值 | 说明 |
|--------|--------|------|
| `asr.provider` | `groq` / `local` | 识别引擎 |
| `asr.local_model` | `tiny` / `base` / `small` / `medium` | 本地模型大小 |
| `asr.language` | `zh` / `en` / `ja` / `ko` / `null` | 默认语言 |
| `asr.use_gpu` | `true` / `false` | GPU 加速开关 |
| `groq_api_key` | API Key 字符串 | Groq API Key |
| `output_lrc_dir` | 路径 或 `none` | LRC 输出目录 |
| `music_dirs` | 文件夹路径 | 默认音乐目录 |

**示例:**
```bash
# 切换到本地引擎
python main.py config set asr.provider local

# 设置语言为中文
python main.py config set asr.language zh

# 启用 GPU
python main.py config set asr.use_gpu true
```

#### 3.5.3 `config path` — 配置文件路径

```bash
python main.py config path
# 输出: C:\Users\...\.music-lyrics-sync\config.json
```

---

### 3.6 `model` — 模型管理

#### 3.6.1 `model list` — 列出模型

```bash
python main.py model list [--json]
```

显示所有可用模型及其安装状态。

**JSON 输出:**
```json
[
  {"name": "tiny", "size": "~144 MB", "desc": "Fastest", "installed": true, "path": "..."},
  {"name": "base", "size": "~139 MB", "desc": "Recommended", "installed": false, "path": null}
]
```

#### 3.6.2 `model info` — 模型详情

```bash
python main.py model info <name> [--json]
```

#### 3.6.3 `model download` — 下载模型

```bash
python main.py model download <name>
```

从 [Echovault 模型 Release v1.0](https://github.com/xiaohaifale-QWQ/echovault-models/releases/tag/v1.0) 下载指定模型到本地缓存（`~/.cache/whisper/`），支持实时进度、断点续传、文件大小及 SHA-256 校验。`medium` 会下载两个分片并原子合并，成功后自动删除分片；合并期间约需 6 GB 可用空间。

---

### 3.7 `gpu` — GPU 管理

#### 3.7.1 `gpu scan` — 扫描显卡

```bash
python main.py gpu scan [--json]
```

检测 NVIDIA 显卡型号和 CUDA 安装状态。

**JSON 输出:**
```json
{"gpu_detected": true, "gpu_name": "NVIDIA GeForce RTX 3060 Ti", "cuda_installed": false}
```

#### 3.7.2 `gpu status` — GPU 状态

```bash
python main.py gpu status [--json]
```

查看当前 GPU 加速配置和 CUDA 可用性。

---

### 3.8 `sync` — 文件同步

#### 3.8.1 `sync compare` — 对比文件夹差异

```bash
python main.py sync compare --dir-a <path> --dir-b <path> [--strict] [--json]
```

对比两个文件夹的文件差异（相对路径、大小、修改时间）。`--strict` 会在大小和时间均接近时继续计算内容哈希。

**JSON 输出:**
```json
{
  "dir_a": "E:/music/",
  "dir_b": "/sdcard/Music/",
  "count": 5,
  "diff": [
    {"file": "song.mp3", "type": "only_in_a", "size_a": 4294061, "size_b": 0}
  ]
}
```

差异类型: `only_in_a`(仅在A) / `only_in_b`(仅在B) / `newer_in_a`(A较新) / `newer_in_b`(B较新) / `conflict`(冲突)

#### 3.8.2 `sync serve` — HTTP 文件服务

```bash
python main.py sync serve [--folder DIR]
```

启动 HTTP 服务器，局域网内其他设备可通过浏览器访问和下载文件。

---

### 3.9 `rename` — 重命名歌曲

```bash
python main.py rename <file> <new_name>
```

重命名音频文件，同时自动同步重命名对应的 LRC 文件。

**示例:**
```bash
python main.py rename "E:/music/old_name.mp3" "new_name.mp3"
# 同时重命名 old_name.lrc -> new_name.lrc
```

---

### 3.10 `mark` — 标记纯音乐

```bash
python main.py mark <file>                         # 以文件所在目录作为音乐库根目录
python main.py mark <file> --folder <library>     # 指定音乐库根目录
python main.py mark <file> --folder <library> --unmark
```

标记持久化存储在 `.musicsync_instrumental.json`。

---

### 3.11 `serve` — 启动服务

```bash
python main.py serve http        # HTTP 文件浏览服务
python main.py serve localsend   # LocalSend 接收（需 GUI）
```

### 3.12 `doctor` — 环境诊断

```bash
python main.py doctor
python main.py doctor --json
```

检查基础依赖、ffmpeg、当前 ASR Provider、API Key 或本地模型是否可用。环境未达到识别条件时退出码为 1。

---

## 四、AI Agent 使用指南

### 4.1 典型工作流

```bash
# 1. 检查环境
python main.py doctor --json
python main.py gpu status --json
python main.py model list --json

# 2. 确保引擎可用
python main.py config set asr.provider local        # 选本地
python main.py config set asr.language zh           # 中文
python main.py model download tiny                   # 如未安装则下载

# 3. 扫描待识别歌曲
python main.py list --status no-lrc --json          # 找无歌词的

# 4. 逐个识别（跟踪进度）
python main.py transcribe "E:/music/song.mp3" --json --quiet

# 5. 验证结果
python main.py lyrics show "E:/music/song.mp3" --json
python main.py info "E:/music/song.mp3" --json
```

### 4.2 批量识别流程

```bash
# 一次性批量识别整个文件夹
python main.py transcribe "E:/music/" --language zh --json --quiet

# 检查结果：如果有失败
python main.py list --status no-lrc --json  # 看剩余未识别的
```

### 4.3 配置切换

```bash
# 云端模式（需要 API Key）
python main.py config set asr.provider groq
python main.py config set groq_api_key "gsk_xxxx"

# 本地模式
python main.py config set asr.provider local
python main.py config set asr.local_model base
```

### 4.4 搜索歌词

```bash
# 找包含特定歌词的歌
python main.py lyrics search "理想" --json

# 查看某首歌的歌词
python main.py lyrics show "E:/music/song.mp3"
```

### 4.5 文件管理

```bash
# 重命名
python main.py rename "E:/music/old.mp3" "new_name.mp3"

# 标记纯音乐（批量识别时会自动跳过）
python main.py mark "E:/music/instrumental.mp3"
```

---

## 五、JSON Schema 参考

### list 输出
```json
[{
  "name": "string",
  "path": "string (absolute)",
  "size": "number (bytes)",
  "size_human": "string",
  "has_lrc": "boolean",
  "folder": "string"
}]
```

### transcribe 输出
```json
{
  "summary": {
    "total": "number",
    "ok": "number",
    "failed": "number",
    "skipped": "number"
  },
  "results": [{
    "file": "string",
    "status": "ok | failed | skipped",
    "lrc_path": "string | null",
    "error": "string | null"
  }]
}
```

### lyrics show 输出
```json
[{
  "ts": "number (seconds)",
  "text": "string"
}]
```

### config show 输出
```json
{
  "music_dirs": ["string"],
  "output_lrc_dir": "string | null",
  "asr": {
    "provider": "groq | local",
    "local_model": "tiny | base | small | medium",
    "language": "zh | en | ja | ko | null",
    "use_vocal_separation": "boolean",
    "use_gpu": "boolean"
  },
  "config_path": "string"
}
```

### model list 输出
```json
[{
  "name": "tiny | base | small | medium",
  "size": "string",
  "desc": "string",
  "installed": "boolean",
  "path": "string | null"
}]
```

### gpu scan 输出
```json
{
  "gpu_detected": "boolean",
  "gpu_name": "string | null",
  "cuda_installed": "boolean"
}
```

### sync compare 输出
```json
{
  "dir_a": "string",
  "dir_b": "string",
  "count": "number",
  "diff": [{
    "file": "string",
    "type": "only_in_a | only_in_b | newer_in_a | newer_in_b | conflict",
    "size_a": "number",
    "size_b": "number"
  }]
}
```

---

## 六、错误处理

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 错误（文件不存在、Provider 不可用、识别失败等） |

所有错误信息输出到 stderr，正常结果输出到 stdout。

---

## 七、与 GUI 操作对应表

| GUI 操作 | CLI 命令 |
|----------|----------|
| 打开文件夹 → 歌曲列表 | `list <folder>` |
| 筛选歌词状态 | `list --status no-lrc` |
| 筛选文件格式 | `list --format mp3` |
| 搜索歌曲 | `list --search <kw>` |
| 点击歌曲 → 详情 | `info <file>` |
| 点击"识别歌词" | `transcribe <file>` |
| 点击"识别全部" | `transcribe <folder>` |
| 歌词预览 | `lyrics show <file>` |
| 设置引擎 | `config set asr.provider <v>` |
| 设置模型 | `config set asr.local_model <v>` |
| 设置语言 | `config set asr.language <v>` |
| 下载模型 | `model download <name>` |
| 扫描显卡 | `gpu scan` |
| 启用 GPU | `config set asr.use_gpu true` |
| 对比文件夹 | `sync compare --dir-a ... --dir-b ...` |
| 双击改名 | `rename <old> <new>` |
| 右键标记纯音乐 | `mark <file>` |
| 设置 API Key | `config set groq_api_key <key>` |
| 设置 LRC 输出目录 | `config set output_lrc_dir <path>` |
