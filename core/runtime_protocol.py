"""Versioned JSON Lines protocol shared by the application and ASR workers."""

import json
from collections.abc import Mapping
from typing import Any

PROTOCOL_VERSION = 1


class RuntimeProtocolError(ValueError):
    """Raised when a worker protocol message is malformed or incompatible."""


def encode_message(message: Mapping[str, Any]) -> str:
    """Encode one protocol message without its trailing newline."""

    if not isinstance(message, Mapping):
        raise RuntimeProtocolError("协议消息必须是对象")
    try:
        return json.dumps(dict(message), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RuntimeProtocolError(f"协议消息无法序列化: {exc}") from exc


def decode_message(raw: str) -> dict[str, Any]:
    """Decode and validate one JSON Lines message."""

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeProtocolError(f"协议消息不是有效 JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise RuntimeProtocolError("协议消息必须是 JSON 对象")

    version = value.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise RuntimeProtocolError(
            f"协议版本不兼容: 收到 {version!r}，需要 {PROTOCOL_VERSION}"
        )
    return value


def make_request(request_id: str, action: str, **payload: Any) -> dict[str, Any]:
    """Create a validated worker request."""

    if not request_id:
        raise RuntimeProtocolError("请求 id 不能为空")
    if not action:
        raise RuntimeProtocolError("请求 action 不能为空")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "id": request_id,
        "action": action,
        **payload,
    }


def make_response(request_id: str | None, message_type: str, **payload: Any) -> dict[str, Any]:
    """Create a worker response with the current protocol version."""

    return {
        "protocol_version": PROTOCOL_VERSION,
        "id": request_id,
        "type": message_type,
        **payload,
    }
