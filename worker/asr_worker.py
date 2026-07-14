"""Source ASR worker implementing the stable JSON Lines control protocol.

Whisper transcription is intentionally added in the next implementation step. This
entry point already provides a real runtime diagnostic command, allowing CPU/CUDA
runtime bundles to validate themselves before being enabled by the GUI.
"""

import logging
import sys
from typing import Any

from core.runtime_protocol import (
    PROTOCOL_VERSION,
    RuntimeProtocolError,
    decode_message,
    encode_message,
    make_response,
)

WORKER_VERSION = "0.1.0"


def _doctor() -> dict[str, Any]:
    report: dict[str, Any] = {
        "worker_version": WORKER_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "torch_installed": False,
        "cuda_available": False,
        "device": "cpu",
    }
    try:
        import torch
    except ImportError:
        return report

    report["torch_installed"] = True
    report["torch_version"] = getattr(torch, "__version__", "unknown")
    report["torch_cuda_version"] = getattr(getattr(torch, "version", None), "cuda", None)
    cuda = getattr(torch, "cuda", None)
    try:
        cuda_available = bool(cuda and cuda.is_available())
    except Exception as exc:  # Runtime/driver failures must not crash diagnostics.
        report["cuda_error"] = str(exc)
        return report

    report["cuda_available"] = cuda_available
    if not cuda_available:
        return report

    report["device"] = "cuda"
    try:
        report["gpu_name"] = cuda.get_device_name(0)
        report["compute_capability"] = list(cuda.get_device_capability(0))
        properties = cuda.get_device_properties(0)
        report["total_memory_mib"] = int(properties.total_memory / 1024 / 1024)
    except Exception as exc:
        report["cuda_error"] = str(exc)
    return report


def _handle(request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    request_id = request.get("id")
    action = request.get("action")
    if not isinstance(request_id, str) or not request_id:
        return make_response(None, "error", code="INVALID_REQUEST", message="请求 id 无效"), False
    if action == "ping":
        return make_response(request_id, "result", data={"worker_version": WORKER_VERSION}), False
    if action == "doctor":
        return make_response(request_id, "result", data=_doctor()), False
    if action == "shutdown":
        return make_response(request_id, "result", data={"stopped": True}), True
    return (
        make_response(
            request_id,
            "error",
            code="UNKNOWN_ACTION",
            message=f"当前 Worker 不支持操作: {action!r}",
            retryable=False,
        ),
        False,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")
    for raw in sys.stdin:
        try:
            request = decode_message(raw)
            response, should_stop = _handle(request)
        except RuntimeProtocolError as exc:
            response = make_response(None, "error", code="INVALID_REQUEST", message=str(exc))
            should_stop = False
        except Exception as exc:  # Keep the protocol alive for unexpected command errors.
            logging.exception("Worker command failed")
            response = make_response(None, "error", code="WORKER_ERROR", message=str(exc))
            should_stop = False
        print(encode_message(response), flush=True)
        if should_stop:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
