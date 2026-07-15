"""讯飞极速录音转写 Provider。

使用讯飞“极速录音转写大模型”HTTP API，适合已录制的完整音频或视频音轨。
接口要求 AppID、API Key 与 API Secret；音频会上传到讯飞完成云端识别。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import time
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Optional

import requests

from core.audio_utils import convert_to_whisper_format, get_audio_info

from .base import ASRProvider, Segment, TranscriptionResult


class XunfeiTranscriptionProvider(ASRProvider):
    """讯飞极速录音转写（适合 5 小时以内的已录制素材）。"""

    _UPLOAD_URL = "https://upload-ost-api.xfyun.cn/file/upload"
    _CREATE_URL = "https://ost-api.xfyun.cn/v2/ost/pro_create"
    _QUERY_URL = "https://ost-api.xfyun.cn/v2/ost/query"
    _MAX_UPLOAD_BYTES = 30 * 1024 * 1024

    def __init__(
        self,
        app_id: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        self._app_id = (app_id or os.environ.get("XUNFEI_APP_ID", "")).strip()
        self._api_key = (api_key or os.environ.get("XUNFEI_API_KEY", "")).strip()
        self._api_secret = (
            api_secret or os.environ.get("XUNFEI_API_SECRET", "")
        ).strip()

    @property
    def name(self) -> str:
        return "xunfei"

    @property
    def display_name(self) -> str:
        return "讯飞极速录音转写（云端）"

    def is_available(self) -> bool:
        return bool(self._app_id and self._api_key and self._api_secret)

    def transcribe(
        self, audio_path: str, language: Optional[str] = None
    ) -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError(
                "讯飞配置不完整。请在“密钥管理”中填写同一应用的 "
                "AppID、API Key 和 API Secret，并开通极速录音转写服务。"
            )
        self._language_type(language)
        source = Path(audio_path)
        if not source.is_file():
            raise FileNotFoundError(audio_path)

        converted_path: Optional[str] = None
        try:
            converted_path = convert_to_whisper_format(str(source))
            converted = Path(converted_path)
            if converted.stat().st_size > self._MAX_UPLOAD_BYTES:
                raise RuntimeError(
                    "讯飞单文件上传当前限制为 30 MB。请使用更短的素材，"
                    "或改用本地/Groq 识别；软件不会把歌曲拆段后上传。"
                )
            duration = float(get_audio_info(converted_path).get("duration", 0.0))
            audio_url = self._upload_file(converted)
            task_id = self._create_task(audio_url, converted.stat().st_size, language, duration)
            response = self._wait_for_result(task_id, duration)
            return self._parse_result(response, language, duration)
        finally:
            if converted_path:
                try:
                    Path(converted_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def _upload_file(self, path: Path) -> str:
        request_id = uuid.uuid4().hex
        content_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
        body, boundary = self._multipart_body(
            fields={"app_id": self._app_id, "request_id": request_id},
            file_name=path.name,
            file_content=path.read_bytes(),
            content_type=content_type,
        )
        response = self._post(
            self._UPLOAD_URL,
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        data = response.get("data") or {}
        if not isinstance(data, dict) or not data.get("url"):
            raise RuntimeError("讯飞上传成功但未返回音频地址。")
        return str(data["url"])

    def _create_task(
        self, audio_url: str, audio_size: int, language: Optional[str], duration: float
    ) -> str:
        language_type = self._language_type(language)
        payload = {
            "common": {"app_id": self._app_id},
            "business": {
                "request_id": uuid.uuid4().hex,
                "language": "zh_cn",
                "domain": "pro_ost_ed",
                "accent": "mandarin",
                "duration": max(1, int(duration)),
                "enable_subtitle": 1,
                "language_type": language_type,
            },
            "data": {
                "audio_url": audio_url,
                "audio_src": "http",
                "audio_size": audio_size,
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
            },
        }
        response = self._post_json(self._CREATE_URL, payload)
        data = response.get("data") or {}
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not task_id:
            raise RuntimeError("讯飞未返回转写任务编号。")
        return str(task_id)

    def _wait_for_result(self, task_id: str, duration: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(120.0, min(900.0, duration * 3 + 120.0))
        last_status = ""
        while time.monotonic() < deadline:
            response = self._post_json(
                self._QUERY_URL,
                {"common": {"app_id": self._app_id}, "business": {"task_id": task_id}},
            )
            data = response.get("data") or {}
            if not isinstance(data, dict):
                raise RuntimeError("讯飞返回了无效的任务状态。")
            status = str(data.get("task_status", ""))
            result = self._json_object(data.get("result"))
            if status in {"3", "4"} and result is not None:
                return result
            if status and status not in {"1", "2", "3", "4"}:
                raise RuntimeError(f"讯飞转写任务失败（状态 {status}）。")
            last_status = status or last_status
            time.sleep(2)
        suffix = f"（最后状态 {last_status}）" if last_status else ""
        raise RuntimeError(f"讯飞转写等待超时{suffix}。")

    @staticmethod
    def _language_type(language: Optional[str]) -> int:
        """Map app language choices to the API's zh_cn language mode."""
        if language in {None, "", "auto"}:
            return 1
        if language == "zh":
            return 2
        if language == "en":
            return 3
        raise RuntimeError("讯飞极速录音转写当前仅支持中文、英文或自动中英混合识别。")

    @staticmethod
    def _json_object(value: Any) -> Optional[dict[str, Any]]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return None
            return decoded if isinstance(decoded, dict) else None
        return None

    def _parse_result(
        self, result: dict[str, Any], language: Optional[str], duration: float
    ) -> TranscriptionResult:
        segments: list[Segment] = []
        for lattice in result.get("lattice") or []:
            if not isinstance(lattice, dict):
                continue
            best = lattice.get("json_1best") or {}
            if isinstance(best, str):
                try:
                    best = json.loads(best)
                except json.JSONDecodeError:
                    continue
            sentence = best.get("st") if isinstance(best, dict) else None
            if not isinstance(sentence, dict):
                continue
            text = self._sentence_text(sentence)
            if not text:
                continue
            start = self._milliseconds(sentence.get("bg", lattice.get("begin", 0)))
            end = self._milliseconds(sentence.get("ed", lattice.get("end", 0)))
            try:
                confidence = float(sentence.get("sc", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            segments.append(Segment(start, max(start, end), text, confidence))
        return TranscriptionResult(
            segments=segments,
            language=language or "zh",
            duration=duration,
        )

    @staticmethod
    def _sentence_text(sentence: dict[str, Any]) -> str:
        parts: list[str] = []
        for result in sentence.get("rt") or []:
            for word in result.get("ws") or []:
                candidates = word.get("cw") or []
                if candidates and isinstance(candidates[0], dict):
                    parts.append(str(candidates[0].get("w", "")))
        return "".join(parts).strip()

    @staticmethod
    def _milliseconds(value: Any) -> float:
        try:
            return float(value) / 1000.0
        except (TypeError, ValueError):
            return 0.0

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._post(url, body, "application/json")

    def _post(self, url: str, body: bytes, content_type: str) -> dict[str, Any]:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc
        request_line = f"POST {parsed.path} HTTP/1.1"
        date = format_datetime(datetime.now(timezone.utc), usegmt=True)
        digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
        signature_origin = (
            f"host: {host}\ndate: {date}\n{request_line}\ndigest: {digest}"
        )
        signature = base64.b64encode(
            hmac.new(
                self._api_secret.encode("utf-8"),
                signature_origin.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        authorization = (
            f'api_key="{self._api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line digest", signature="{signature}"'
        )
        headers = {
            "host": host,
            "date": date,
            "digest": digest,
            "authorization": authorization,
            "content-type": content_type,
        }
        try:
            response = requests.post(url, data=body, headers=headers, timeout=(15, 120))
        except requests.RequestException as exc:
            raise RuntimeError(f"无法连接讯飞服务：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"讯飞服务返回了无效响应（HTTP {response.status_code}）。") from exc
        if response.status_code >= 400:
            raise RuntimeError(self._response_error(payload, response.status_code))
        if not isinstance(payload, dict):
            raise RuntimeError("讯飞服务返回了无效响应。")
        if int(payload.get("code", -1)) != 0:
            raise RuntimeError(self._response_error(payload, response.status_code))
        return payload

    def _response_error(self, payload: Any, status_code: int) -> str:
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("desc") or "未知错误"
            code = payload.get("code")
            if str(code) == "11200":
                return (
                    "讯飞极速录音转写未获授权（错误码 11200）。当前 AppID 未开通该服务、"
                    "授权已过期或额度许可不可用；请在讯飞控制台为同一 AppID 开通"
                    "“极速录音转写”后重试。"
                )
            if str(code) == "11201":
                return "讯飞极速录音转写当日授权额度已用完（错误码 11201）。"
            return f"讯飞识别失败（HTTP {status_code}，错误码 {code}）：{message}"
        return f"讯飞识别失败（HTTP {status_code}）。"

    @staticmethod
    def _multipart_body(
        fields: dict[str, str], file_name: str, file_content: bytes, content_type: str
    ) -> tuple[bytes, str]:
        boundary = f"----Echovault{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )
        safe_name = file_name.replace('"', "_")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    "Content-Disposition: form-data; "
                    f'name="data"; filename="{safe_name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_content,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        return b"".join(chunks), boundary
