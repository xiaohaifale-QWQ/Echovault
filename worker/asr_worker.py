"""Source ASR worker implementing the stable JSON Lines control protocol.

Whisper transcription is intentionally added in the next implementation step. This
entry point already provides a real runtime diagnostic command, allowing CPU/CUDA
runtime bundles to validate themselves before being enabled by the GUI.
"""

import logging
import sys
from typing import Any, Callable

from core.runtime_protocol import (
    PROTOCOL_VERSION,
    RuntimeProtocolError,
    decode_message,
    encode_message,
    make_response,
)
from worker.whisper_service import WhisperService, WorkerCommandError

WORKER_VERSION = "0.1.0"


def _handle(
    request: dict[str, Any],
    service: WhisperService,
    progress: Callable[[int, str], None],
) -> tuple[dict[str, Any], bool]:
    request_id = request.get("id")
    action = request.get("action")
    if not isinstance(request_id, str) or not request_id:
        return make_response(None, "error", code="INVALID_REQUEST", message="请求 id 无效"), False
    if action == "ping":
        return make_response(request_id, "result", data={"worker_version": WORKER_VERSION}), False
    if action == "doctor":
        report = {
            "worker_version": WORKER_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            **service.doctor(),
        }
        return (
            make_response(request_id, "result", data=report),
            False,
        )
    if action == "transcribe":
        try:
            data = service.transcribe(
                str(request.get("audio", "")),
                str(request.get("model", "base")),
                request.get("language") if isinstance(request.get("language"), str) else None,
                request.get("cache_dir") if isinstance(request.get("cache_dir"), str) else None,
                progress=progress,
            )
        except WorkerCommandError as exc:
            return (
                make_response(
                    request_id,
                    "error",
                    code=exc.code,
                    message=str(exc),
                    retryable=exc.retryable,
                ),
                False,
            )
        return make_response(request_id, "result", data=data), False
    if action == "release_model":
        service.release_model()
        return make_response(request_id, "result", data={"released": True}), False
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
    service = WhisperService()
    for raw in sys.stdin:
        request_id: str | None = None
        try:
            request = decode_message(raw)
            request_id = request.get("id") if isinstance(request.get("id"), str) else None

            def progress(percent: int, message: str) -> None:
                print(
                    encode_message(
                        make_response(request_id, "progress", percent=percent, message=message)
                    ),
                    flush=True,
                )

            response, should_stop = _handle(request, service, progress)
        except RuntimeProtocolError as exc:
            response = make_response(None, "error", code="INVALID_REQUEST", message=str(exc))
            should_stop = False
        except Exception as exc:  # Keep the protocol alive for unexpected command errors.
            logging.exception("Worker command failed")
            response = make_response(None, "error", code="WORKER_ERROR", message=str(exc))
            should_stop = False
        print(encode_message(response), flush=True)
        if should_stop:
            service.release_model()
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
