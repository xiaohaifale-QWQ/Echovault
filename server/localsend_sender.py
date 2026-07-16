"""LocalSend Protocol v2.1 device model and upload client."""

from __future__ import annotations

import hashlib
import http.client
import json
import mimetypes
import ssl
import threading
import urllib.parse
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from core.transfer_session import file_sha256


@dataclass(frozen=True)
class LocalSendDevice:
    alias: str
    ip: str
    port: int = 53317
    protocol: str = "https"
    fingerprint: str = ""
    device_type: str = "mobile"
    version: str = "2.0"
    last_seen: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "LocalSendDevice":
        return cls(
            alias=str(payload.get("alias") or payload.get("ip") or "未知设备"),
            ip=str(payload.get("ip", "")),
            port=int(payload.get("port") or 53317),
            protocol=str(payload.get("protocol") or "https"),
            fingerprint=str(payload.get("fingerprint") or "").lower().replace(":", ""),
            device_type=str(payload.get("deviceType") or payload.get("device_type") or "mobile"),
            version=str(payload.get("version") or "2.0"),
            last_seen=str(payload.get("last_seen") or ""),
        )

    def as_dict(self) -> dict:
        return asdict(self)


class LocalSendError(RuntimeError):
    pass


class LocalSendSender:
    def __init__(self, alias: str = "Echovault"):
        self.alias = alias
        self.fingerprint = uuid.uuid4().hex

    def _connection(self, device: LocalSendDevice):
        if device.protocol == "https":
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            connection = http.client.HTTPSConnection(
                device.ip, device.port, timeout=15, context=context
            )
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True)
            actual = hashlib.sha256(certificate).hexdigest()
            if device.fingerprint and actual != device.fingerprint:
                connection.close()
                raise LocalSendError("目标设备证书指纹与发现信息不一致。")
            return connection
        return http.client.HTTPConnection(device.ip, device.port, timeout=15)

    def _json_request(
        self,
        device: LocalSendDevice,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict]:
        connection = self._connection(device)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else b""
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            raw = response.read()
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return response.status, data
        finally:
            connection.close()

    def _upload_file(
        self,
        device: LocalSendDevice,
        *,
        session_id: str,
        file_id: str,
        token: str,
        path: Path,
        progress: Callable[[int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> int:
        query = urllib.parse.urlencode(
            {"sessionId": session_id, "fileId": file_id, "token": token}
        )
        connection = self._connection(device)
        try:
            connection.putrequest("POST", f"/api/localsend/v2/upload?{query}")
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(path.stat().st_size))
            connection.endheaders()
            sent = 0
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(256 * 1024), b""):
                    if cancel_event and cancel_event.is_set():
                        raise LocalSendError("发送已取消。")
                    connection.send(chunk)
                    sent += len(chunk)
                    if progress:
                        progress(sent)
            response = connection.getresponse()
            response.read()
            if response.status not in {200, 204}:
                raise LocalSendError(f"目标设备接收失败，HTTP {response.status}。")
            return sent
        finally:
            connection.close()

    def send_files(
        self,
        device: LocalSendDevice,
        files: list[str | Path],
        *,
        progress: Callable[[str, int, int, int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[dict]:
        paths = [Path(path).resolve() for path in files if Path(path).is_file()]
        if not paths:
            raise LocalSendError("没有可发送的文件。")
        ids = {uuid.uuid4().hex: path for path in paths}
        request_files = {}
        for file_id, path in ids.items():
            request_files[file_id] = {
                "id": file_id,
                "fileName": path.name,
                "size": path.stat().st_size,
                "fileType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "sha256": file_sha256(path),
            }
        payload = {
            "info": {
                "alias": self.alias,
                "version": "2.0",
                "deviceModel": "Windows",
                "deviceType": "desktop",
                "fingerprint": self.fingerprint,
                "port": 53317,
                "protocol": "https",
                "download": True,
            },
            "files": request_files,
        }
        status, response = self._json_request(
            device, "POST", "/api/localsend/v2/prepare-upload", payload
        )
        if status == 204:
            return [{"path": str(path), "status": "skipped"} for path in paths]
        messages = {
            401: "手机要求 PIN 或 PIN 不正确。",
            403: "手机拒绝了本次传输。",
            409: "手机正在处理另一项传输。",
            429: "手机请求过多，请稍后重试。",
        }
        if status != 200:
            raise LocalSendError(messages.get(status, f"准备发送失败，HTTP {status}。"))
        session_id = str(response.get("sessionId", ""))
        tokens = dict(response.get("files", {}))
        if not session_id or not tokens:
            raise LocalSendError("手机没有返回有效的传输会话。")

        total_size = sum(path.stat().st_size for path in paths)
        completed_size = 0
        results = []
        try:
            for index, (file_id, path) in enumerate(ids.items(), 1):
                token = tokens.get(file_id)
                if not token:
                    results.append({"path": str(path), "status": "skipped"})
                    continue

                def on_file_progress(sent: int, *, base=completed_size, current=path):
                    if progress:
                        progress(
                            str(current),
                            sent,
                            current.stat().st_size,
                            base + sent,
                            total_size,
                        )

                self._upload_file(
                    device,
                    session_id=session_id,
                    file_id=file_id,
                    token=token,
                    path=path,
                    progress=on_file_progress,
                    cancel_event=cancel_event,
                )
                completed_size += path.stat().st_size
                results.append({"path": str(path), "status": "sent", "index": index})
        except Exception:
            query = urllib.parse.urlencode({"sessionId": session_id})
            try:
                self._json_request(device, "POST", f"/api/localsend/v2/cancel?{query}")
            except Exception:
                pass
            raise
        return results
