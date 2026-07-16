"""讯飞云端录音转写 Provider。

优先使用“极速录音转写大模型”HTTP API；当前 AppID 未开通或额度耗尽时，
自动改用更常见的“语音听写（流式版）”WebSocket API。接口要求 AppID、
API Key 与 API Secret；音频会上传到讯飞完成云端识别。
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
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import websocket

from core.audio_utils import convert_to_whisper_format, get_audio_info

from .base import ASRProvider, Segment, TranscriptionResult


class XunfeiAPIError(RuntimeError):
    """讯飞返回了可识别的业务错误码。"""

    def __init__(self, code: Any, message: str, status_code: int = 0):
        super().__init__(message)
        self.code = str(code)
        self.status_code = status_code


class XunfeiStreamClosedError(RuntimeError):
    """流式听写因端点检测提前关闭，需要缩短音频片段重试。"""


class XunfeiTranscriptionProvider(ASRProvider):
    """讯飞极速录音转写与流式语音听写兼容 Provider。"""

    _UPLOAD_URL = "https://upload-ost-api.xfyun.cn/file/upload"
    _CREATE_URL = "https://ost-api.xfyun.cn/v2/ost/pro_create"
    _QUERY_URL = "https://ost-api.xfyun.cn/v2/ost/query"
    _MAX_UPLOAD_BYTES = 30 * 1024 * 1024
    _IAT_URL = "wss://iat-api.xfyun.cn/v2/iat"
    _IAT_CHUNK_SECONDS = 50
    _IAT_RETRY_SECONDS = 8
    _IAT_EOS_SECONDS = 10
    _IAT_FRAME_BYTES = 1280
    _IAT_MAX_WORKERS = 4
    _SPEED_FALLBACK_CODES = {"11200", "11201"}
    _LEADING_PUNCTUATION = frozenset("，。！？；：、,.!?;:")

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
        self._speed_transcription_available: Optional[bool] = None

    @property
    def name(self) -> str:
        return "xunfei"

    @property
    def display_name(self) -> str:
        return "讯飞云端识别（极速转写 / 流式听写）"

    def is_available(self) -> bool:
        return bool(self._app_id and self._api_key and self._api_secret)

    def transcribe(
        self, audio_path: str, language: Optional[str] = None
    ) -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError(
                "讯飞配置不完整。请在“密钥管理”中填写同一应用的 "
                "AppID、API Key 和 API Secret，并至少开通“语音听写（流式版）”"
                "或“极速录音转写”服务。"
            )
        self._language_type(language)
        source = Path(audio_path)
        if not source.is_file():
            raise FileNotFoundError(audio_path)

        converted_path: Optional[str] = None
        try:
            converted_path = convert_to_whisper_format(str(source))
            converted = Path(converted_path)
            duration = float(get_audio_info(converted_path).get("duration", 0.0))
            if (
                self._speed_transcription_available is not False
                and converted.stat().st_size <= self._MAX_UPLOAD_BYTES
            ):
                try:
                    audio_url = self._upload_file(converted)
                    task_id = self._create_task(
                        audio_url,
                        converted.stat().st_size,
                        language,
                        duration,
                    )
                    response = self._wait_for_result(task_id, duration)
                    self._speed_transcription_available = True
                    return self._parse_result(response, language, duration)
                except XunfeiAPIError as exc:
                    if exc.code not in self._SPEED_FALLBACK_CODES:
                        raise
                    self._speed_transcription_available = False
                    speed_error = str(exc)
            else:
                speed_error = (
                    "音频超过极速接口 30 MB 小文件上传限制"
                    if converted.stat().st_size > self._MAX_UPLOAD_BYTES
                    else "当前应用未启用讯飞极速录音转写"
                )
            try:
                return self._transcribe_streaming(converted, language, duration)
            except Exception as exc:
                raise RuntimeError(
                    f"{speed_error}；已自动切换“语音听写（流式版）”，"
                    f"但流式识别失败：{exc}"
                ) from exc
        finally:
            if converted_path:
                try:
                    Path(converted_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def _transcribe_streaming(
        self,
        path: Path,
        language: Optional[str],
        duration: float,
    ) -> TranscriptionResult:
        """Use the commonly enabled 60-second streaming dictation API."""
        pcm_data, sample_rate = self._read_pcm_wave(path)
        bytes_per_second = sample_rate * 2
        chunk_bytes = self._IAT_CHUNK_SECONDS * bytes_per_second
        chunks = [
            (offset / bytes_per_second, pcm_data[offset : offset + chunk_bytes])
            for offset in range(0, len(pcm_data), chunk_bytes)
        ]
        if not chunks:
            return TranscriptionResult(
                segments=[],
                language=language or "zh",
                duration=duration,
            )

        results: list[tuple[int, list[Segment]]] = []
        max_workers = min(self._IAT_MAX_WORKERS, len(chunks))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._transcribe_streaming_chunk_resilient,
                    audio_data,
                    language,
                    offset,
                ): index
                for index, (offset, audio_data) in enumerate(chunks)
            }
            for future in as_completed(futures):
                results.append((futures[future], future.result()))

        segments = [
            segment
            for _index, chunk_segments in sorted(results)
            for segment in chunk_segments
        ]
        return TranscriptionResult(
            segments=self._normalize_streaming_segments(segments),
            language=language or "zh",
            duration=duration,
        )

    @staticmethod
    def _read_pcm_wave(path: Path) -> tuple[bytes, int]:
        try:
            with wave.open(str(path), "rb") as audio:
                channels = audio.getnchannels()
                sample_width = audio.getsampwidth()
                sample_rate = audio.getframerate()
                compression = audio.getcomptype()
                pcm_data = audio.readframes(audio.getnframes())
        except (OSError, wave.Error) as exc:
            raise RuntimeError(f"无法读取讯飞流式识别音频：{exc}") from exc
        if (
            channels != 1
            or sample_width != 2
            or sample_rate != 16000
            or compression != "NONE"
        ):
            raise RuntimeError(
                "讯飞流式识别需要 16 kHz、16-bit、单声道 PCM 音频。"
            )
        return pcm_data, sample_rate

    def _transcribe_streaming_chunk_resilient(
        self,
        audio_data: bytes,
        language: Optional[str],
        offset: float,
    ) -> list[Segment]:
        try:
            segments = self._transcribe_streaming_chunk(
                audio_data,
                language,
                offset,
            )
        except XunfeiStreamClosedError:
            return self._retry_streaming_tail(audio_data, language, offset, 0.0)

        chunk_duration = len(audio_data) / 32000
        if chunk_duration <= self._IAT_RETRY_SECONDS:
            return segments
        coverage_end = max(
            (segment.end_time - offset for segment in segments),
            default=0.0,
        )
        if chunk_duration - coverage_end <= self._IAT_EOS_SECONDS:
            return segments
        retry_start = max(0.0, coverage_end + 0.5) if segments else 0.0
        return segments + self._retry_streaming_tail(
            audio_data,
            language,
            offset,
            retry_start,
        )

    def _retry_streaming_tail(
        self,
        audio_data: bytes,
        language: Optional[str],
        offset: float,
        start_seconds: float,
    ) -> list[Segment]:
        retry_bytes = self._IAT_RETRY_SECONDS * 32000
        start_byte = min(len(audio_data), int(start_seconds * 32000))
        start_byte -= start_byte % 2
        segments: list[Segment] = []
        for byte_offset in range(start_byte, len(audio_data), retry_bytes):
            retry_data = audio_data[byte_offset : byte_offset + retry_bytes]
            retry_offset = offset + byte_offset / 32000
            segments.extend(
                self._transcribe_streaming_chunk(
                    retry_data,
                    language,
                    retry_offset,
                )
            )
        return segments

    def _transcribe_streaming_chunk(
        self,
        audio_data: bytes,
        language: Optional[str],
        offset: float,
    ) -> list[Segment]:
        url = self._streaming_auth_url()
        try:
            connection = websocket.create_connection(url, timeout=20)
        except Exception as exc:
            raise RuntimeError(f"无法连接讯飞流式听写服务：{exc}") from exc

        packets: list[dict[str, Any]] = []
        try:
            for index in range(0, len(audio_data), self._IAT_FRAME_BYTES):
                frame = audio_data[index : index + self._IAT_FRAME_BYTES]
                payload: dict[str, Any] = {
                    "data": {
                        "status": 0 if index == 0 else 1,
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": base64.b64encode(frame).decode("ascii"),
                    }
                }
                if index == 0:
                    payload["common"] = {"app_id": self._app_id}
                    payload["business"] = self._streaming_business(language)
                connection.send(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                time.sleep(0.04)
            connection.send(
                json.dumps(
                    {"data": {"status": 2}},
                    separators=(",", ":"),
                )
            )

            while True:
                try:
                    raw_message = connection.recv()
                    if not raw_message:
                        raise XunfeiStreamClosedError(
                            "讯飞在返回最终结果前关闭了流式连接。"
                        )
                    message = json.loads(raw_message)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("讯飞流式听写返回了无效 JSON。") from exc
                code = message.get("code", -1)
                if int(code) != 0:
                    detail = message.get("message") or "未知错误"
                    raise XunfeiAPIError(
                        code,
                        f"讯飞流式听写失败（错误码 {code}）：{detail}",
                    )
                packets.append(message)
                if (message.get("data") or {}).get("status") == 2:
                    break
        except websocket.WebSocketConnectionClosedException as exc:
            raise XunfeiStreamClosedError(
                "讯飞因长静音或端点检测提前关闭了流式连接。"
            ) from exc
        except websocket.WebSocketException as exc:
            raise RuntimeError(f"讯飞流式听写连接中断：{exc}") from exc
        finally:
            connection.close()
        return self._parse_streaming_packets(packets, offset, len(audio_data) / 32000)

    @staticmethod
    def _streaming_business(language: Optional[str]) -> dict[str, Any]:
        if language == "en":
            return {
                "language": "en_us",
                "domain": "iat",
                "vinfo": 1,
                "ptt": 1,
                "eos": 10000,
            }
        return {
            "language": "zh_cn",
            "domain": "iat",
            "accent": "mandarin",
            "vinfo": 1,
            "ptt": 1,
            "eos": 10000,
            "rlang": "zh-cn",
        }

    def _streaming_auth_url(self) -> str:
        host = "iat-api.xfyun.cn"
        request_path = "/v2/iat"
        date = format_datetime(datetime.now(timezone.utc), usegmt=True)
        signature_origin = (
            f"host: {host}\ndate: {date}\nGET {request_path} HTTP/1.1"
        )
        signature = base64.b64encode(
            hmac.new(
                self._api_secret.encode("utf-8"),
                signature_origin.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        authorization_origin = (
            f'api_key="{self._api_key}", algorithm="hmac-sha256", '
            'headers="host date request-line", '
            f'signature="{signature}"'
        )
        authorization = base64.b64encode(
            authorization_origin.encode("utf-8")
        ).decode("ascii")
        query = urlencode(
            {
                "authorization": authorization,
                "date": date,
                "host": host,
            }
        )
        return f"{self._IAT_URL}?{query}"

    @classmethod
    def _parse_streaming_packets(
        cls,
        packets: list[dict[str, Any]],
        offset: float,
        chunk_duration: float,
    ) -> list[Segment]:
        segments: list[Segment] = []
        fallback_cursor = 0.0
        for packet in packets:
            result = ((packet.get("data") or {}).get("result") or {})
            if not isinstance(result, dict):
                continue
            text, confidence = cls._streaming_text(result)
            if not text:
                continue
            start, end = cls._streaming_time_range(result)
            if end <= start:
                start = fallback_cursor
                end = min(
                    chunk_duration,
                    start + max(0.5, min(8.0, len(text) * 0.25)),
                )
            fallback_cursor = max(fallback_cursor, end)
            segments.append(
                Segment(
                    start_time=offset + start,
                    end_time=offset + max(start, end),
                    text=text,
                    confidence=confidence,
                )
            )
        return segments

    @staticmethod
    def _streaming_text(result: dict[str, Any]) -> tuple[str, float]:
        parts: list[str] = []
        confidences: list[float] = []
        for word in result.get("ws") or []:
            candidates = word.get("cw") or []
            if not candidates or not isinstance(candidates[0], dict):
                continue
            candidate = candidates[0]
            parts.append(str(candidate.get("w", "")))
            try:
                score = float(candidate.get("sc", 0))
            except (TypeError, ValueError):
                score = 0.0
            if score > 0:
                confidences.append(score)
        confidence = sum(confidences) / len(confidences) if confidences else 1.0
        return "".join(parts).strip(), confidence

    @staticmethod
    def _streaming_time_range(result: dict[str, Any]) -> tuple[float, float]:
        vad = result.get("vad") or {}
        ranges = vad.get("ws") if isinstance(vad, dict) else None
        if not isinstance(ranges, list):
            return 0.0, 0.0
        starts: list[float] = []
        ends: list[float] = []
        for item in ranges:
            if not isinstance(item, dict):
                continue
            try:
                starts.append(float(item.get("bg", 0)) * 0.01)
                ends.append(float(item.get("ed", 0)) * 0.01)
            except (TypeError, ValueError):
                continue
        return (min(starts), max(ends)) if starts and ends else (0.0, 0.0)

    @classmethod
    def _normalize_streaming_segments(
        cls,
        segments: list[Segment],
    ) -> list[Segment]:
        """Attach punctuation-only packets to the sentence they complete."""
        normalized: list[Segment] = []
        for segment in segments:
            text = segment.text.strip()
            leading = ""
            while text and text[0] in cls._LEADING_PUNCTUATION:
                leading += text[0]
                text = text[1:].lstrip()
            if leading and normalized:
                normalized[-1].text = normalized[-1].text.rstrip() + leading
                normalized[-1].end_time = max(
                    normalized[-1].end_time,
                    segment.start_time,
                )
            if not text:
                if normalized:
                    normalized[-1].end_time = max(
                        normalized[-1].end_time,
                        segment.end_time,
                    )
                continue
            segment.text = text
            normalized.append(segment)
        return normalized

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
        raise RuntimeError("讯飞云端识别当前仅支持中文、英文或自动中英混合识别。")

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
            code = payload.get("code") if isinstance(payload, dict) else None
            raise XunfeiAPIError(
                code,
                self._response_error(payload, response.status_code),
                response.status_code,
            )
        if not isinstance(payload, dict):
            raise RuntimeError("讯飞服务返回了无效响应。")
        if int(payload.get("code", -1)) != 0:
            raise XunfeiAPIError(
                payload.get("code"),
                self._response_error(payload, response.status_code),
                response.status_code,
            )
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
