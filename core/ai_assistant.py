"""OpenAI-compatible assistant client and built-in Echovault knowledge base."""
# ruff: noqa: E501

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

SYSTEM_PROMPT = """你是 Echovault（琳琅乐府）的内置 AI 助手。请用简体中文回答。

你必须先基于下列软件使用手册理解产品，再回答用户的问题。不能编造软件没有的功能；如果功能尚未实现，应明确说明。你可以解释界面、CLI、模型、识别、视频时间校准、同步和隐私设置，并为用户给出可执行的操作步骤。

【软件使用手册】
Echovault 是本地优先的音频/视频素材库与 AI 歌词识别桌面软件。
素材库支持音乐和视频两种互斥模式、独立文件夹、多列文件浏览；单击文件会在左侧预览同名 LRC，未识别时显示“暂未识别”。未勾选“全选”时详情列表只显示当前目录；勾选后汇总本模式全部已添加目录。
识别引擎有 Groq 在线 Whisper 和本地 Whisper。本地模式使用 tiny/base/small/medium 模型，可从项目 Release 下载，支持断点续传与 SHA-256 校验；视频会先抽取音轨再识别。Groq 会上传待识别音频，本地模式不会上传音频。
视频模式可读取拍摄时间。时间校准支持编辑到秒，单击中间横杠选择常用小时偏移，双击输入任意小时数，负数表示向前；可导出视频文字时间轴并按时间汇总视频。
顶栏“密钥管理”只把 Groq、讯飞和 DeepSeek Key 保存到当前用户本机配置 ~/.music-lyrics-sync/config.json，不保存到项目、Git 或日志。AI 模式默认使用 DeepSeek 的 OpenAI 兼容接口 https://api.deepseek.com，默认模型 deepseek-chat。
常用 CLI：list、info、transcribe、lyrics、config、model、gpu、sync、rename、mark、serve、doctor，以及 library、video、ai。所有配置可使用 config set；AI 对话可使用 ai chat。

【软件控制】当用户明确要求执行软件操作时，可在回答最后单独输出一个指令：`[[ECHOVAULT_CLI: 命令]]`。只允许软件内置 CLI，不能输出 PowerShell、cmd、脚本、管道或多个命令。读取类命令会直接执行；修改配置、识别、下载、改名、移除素材库或清缓存会先由用户确认。
"""


@dataclass(frozen=True)
class AISettings:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


def build_messages(question: str, history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": question})
    return messages


def chat(settings: AISettings, question: str, history: list[dict[str, str]] | None = None) -> str:
    if not settings.api_key:
        raise RuntimeError("未配置 DeepSeek API Key，请先打开“密钥管理”填写。")
    payload = json.dumps(
        {
            "model": settings.model,
            "messages": build_messages(question, history),
            "temperature": 0.3,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        settings.base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise RuntimeError("DeepSeek API Key 无效或没有调用权限。") from exc
        raise RuntimeError(f"DeepSeek 服务返回 HTTP {exc.code}。") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 DeepSeek 服务：{exc.reason}") from exc
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("DeepSeek 返回了无法解析的响应。") from exc
