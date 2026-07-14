"""Client for the external, versioned Echovault ASR worker process."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.runtime_protocol import decode_message, encode_message, make_request


class WorkerClientError(RuntimeError):
    """Base error raised while communicating with an ASR worker."""


class WorkerRemoteError(WorkerClientError):
    """A structured error returned by the worker."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


ProgressCallback = Callable[[Mapping[str, Any]], None]


class WorkerClient:
    """Run one ASR worker and exchange requests through JSON Lines.

    Requests are intentionally serialized: a worker owns one loaded Whisper model and
    should process one transcription at a time. The client still reads stdout on a
    background thread so request timeouts work reliably on Windows pipes.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("Worker command 不能为空")
        self._command = list(command)
        self._cwd = cwd
        self._env = dict(env) if env is not None else None
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[str | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._request_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.is_running:
            return
        self.close(force=True)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            self._command,
            cwd=self._cwd,
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags if os.name == "nt" else 0,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def request(
        self,
        action: str,
        *,
        timeout: float = 30.0,
        on_progress: ProgressCallback | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        """Send one request and wait for its terminal result."""

        with self._request_lock:
            self.start()
            process = self._process
            if process is None or process.stdin is None:
                raise WorkerClientError("ASR Worker 未能启动")

            request_id = uuid.uuid4().hex
            request = make_request(request_id, action, **payload)
            try:
                process.stdin.write(encode_message(request) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise WorkerClientError(self._worker_exit_message("ASR Worker 已退出")) from exc

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerClientError(f"ASR Worker 请求超时: {action}")
                try:
                    raw = self._messages.get(timeout=remaining)
                except queue.Empty as exc:
                    raise WorkerClientError(f"ASR Worker 请求超时: {action}") from exc
                if raw is None:
                    raise WorkerClientError(self._worker_exit_message("ASR Worker 已退出"))

                message = decode_message(raw)
                if message.get("id") != request_id:
                    raise WorkerClientError("ASR Worker 返回了不匹配的请求 id")

                message_type = message.get("type")
                if message_type == "progress":
                    if on_progress is not None:
                        on_progress(message)
                    continue
                if message_type == "error":
                    raise WorkerRemoteError(
                        str(message.get("code", "WORKER_ERROR")),
                        str(message.get("message", "ASR Worker 执行失败")),
                        retryable=bool(message.get("retryable", False)),
                    )
                if message_type == "result":
                    data = message.get("data", {})
                    if not isinstance(data, dict):
                        raise WorkerClientError("ASR Worker 返回的 result.data 无效")
                    return data
                raise WorkerClientError(f"ASR Worker 返回了未知消息类型: {message_type!r}")

    def close(self, *, force: bool = False) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None and not force:
            try:
                self.request("shutdown", timeout=3.0)
            except WorkerClientError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
        self._process = None

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._messages.put(line.rstrip("\r\n"))
        self._messages.put(None)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip())
            del self._stderr_lines[:-20]

    def _worker_exit_message(self, prefix: str) -> str:
        details = "\n".join(self._stderr_lines[-5:]).strip()
        return f"{prefix}: {details}" if details else prefix
