"""
LocalSend 协议接收端 (HTTPS)

实现 LocalSend Protocol v2.1，让 MusicSync 在局域网中
作为一个 LocalSend 设备出现。手机端的 LocalSend App
可以直接发现本机并将音乐文件发送到指定文件夹。

协议详情: https://github.com/localsend/protocol
"""

import os
import json
import uuid
import socket
import struct
import ssl
import hashlib
import logging
import tempfile
import threading
import datetime
from pathlib import Path
from typing import Optional, Callable
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

MULTICAST_GROUP = "224.0.0.167"
MULTICAST_PORT = 53317
HTTP_PORT = 53317
PROTOCOL_VERSION = "2.0"
DEVICE_TYPE = "desktop"


class LocalSendReceiver:
    """LocalSend 协议接收端 (HTTPS)"""
    
    def __init__(
        self,
        save_dir: str,
        alias: str = "MusicSync",
        on_file_received: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
    ):
        self.save_dir = Path(save_dir)
        self.alias = alias
        self.on_file_received = on_file_received
        self.on_progress = on_progress
        self.fingerprint = ""
        self._cert_file: Optional[str] = None
        
        self._http_server: Optional[HTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._udp_socket: Optional[socket.socket] = None
        self._udp_thread: Optional[threading.Thread] = None
        self._running = False
        self._sessions: dict = {}
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def start(self):
        if self._running:
            return
        
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        
        # 生成 HTTPS 自签名证书
        self._generate_cert()
        
        # 启动 HTTPS 服务器
        self._start_https_server()
        
        # UDP 多播（可选）
        try:
            self._start_udp_multicast()
            self._send_announcement()
        except Exception as e:
            logger.warning(f"UDP 多播启动失败: {e}")
        
        ip = self._get_local_ip()
        logger.info(f"LocalSend 接收端已启动: {self.alias} @ {ip}:{HTTP_PORT} (HTTPS)")
    
    def stop(self):
        self._running = False
        if self._http_server:
            self._http_server.shutdown()
        if self._udp_socket:
            self._udp_socket.close()
        if self._cert_file and os.path.exists(self._cert_file):
            try:
                os.unlink(self._cert_file)
            except Exception:
                pass
        logger.info("LocalSend 接收端已停止")
    
    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    # ─── HTTPS 证书 ─────────────────────────
    
    def _generate_cert(self):
        """生成自签名证书"""
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MusicSync")])
        
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .sign(key, hashes.SHA256())
        )
        
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        tmp.write(cert_pem + key_pem)
        tmp.close()
        self._cert_file = tmp.name
        
        self.fingerprint = hashlib.sha256(cert_pem).hexdigest()
        logger.info(f"HTTPS 证书已生成")
    
    # ─── HTTPS 服务器 ───────────────────────
    
    def _start_https_server(self):
        receiver = self
        
        class LocalSendHandler(BaseHTTPRequestHandler):
            
            def log_message(self, format, *args):
                pass  # 减少日志噪音
            
            def _send_json(self, data: dict, status: int = 200):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            
            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    return {}
                return json.loads(self.rfile.read(length))
            
            def do_POST(self):
                path = self.path.split("?")[0]
                if path == "/api/localsend/v2/register":
                    self._handle_register()
                elif path == "/api/localsend/v2/prepare-upload":
                    self._handle_prepare_upload()
                elif path == "/api/localsend/v2/upload":
                    self._handle_upload()
                elif path == "/api/localsend/v2/cancel":
                    self._handle_cancel()
                else:
                    self._send_json({"message": "not found"}, 404)
            
            def do_GET(self):
                if self.path.split("?")[0] == "/api/localsend/v2/info":
                    self._handle_info()
                else:
                    self._send_json({"message": "not found"}, 404)
            
            def _handle_register(self):
                data = {}
                try:
                    data = self._read_json()
                except Exception:
                    pass
                logger.info(f"设备注册: {data.get('alias', 'unknown')}")
                self._send_json({
                    "alias": receiver.alias,
                    "version": PROTOCOL_VERSION,
                    "deviceModel": "Windows",
                    "deviceType": DEVICE_TYPE,
                    "fingerprint": receiver.fingerprint,
                    "port": HTTP_PORT,
                    "protocol": "https",
                    "download": True,
                })
            
            def _handle_prepare_upload(self):
                try:
                    data = self._read_json()
                except Exception:
                    self._send_json({"message": "Invalid body"}, 400)
                    return
                
                files_info = data.get("files", {})
                sender_alias = data.get("info", {}).get("alias", "unknown")
                
                session_id = uuid.uuid4().hex[:12]
                file_tokens = {}
                skipped = 0
                session_files = {}
                
                for file_id, info in files_info.items():
                    name = info.get("fileName", "unknown")
                    size = info.get("size", 0)
                    
                    existing = receiver.save_dir / Path(name).name
                    if existing.exists() and existing.stat().st_size == size:
                        logger.info(f"跳过重复: {name}")
                        skipped += 1
                        continue
                    
                    token = uuid.uuid4().hex[:16]
                    file_tokens[file_id] = token
                    session_files[file_id] = {"name": name, "size": size, "token": token}
                
                if skipped:
                    logger.info(f"跳过 {skipped} 个重复文件")
                
                if not session_files:
                    logger.info("全部跳过，无需传输")
                    self.send_response(204)
                    self.end_headers()
                    return
                
                receiver._sessions[session_id] = {"files": session_files, "sender": sender_alias}
                
                logger.info(f"上传请求: {sender_alias}, {len(session_files)} 文件, session={session_id}")
                self._send_json({"sessionId": session_id, "files": file_tokens})
            
            def _handle_upload(self):
                query = {}
                if "?" in self.path:
                    import urllib.parse
                    query = dict(urllib.parse.parse_qsl(self.path.split("?")[1]))
                
                session_id = query.get("sessionId", "")
                file_id = query.get("fileId", "")
                token = query.get("token", "")
                
                session = receiver._sessions.get(session_id)
                if not session:
                    self._send_json({"message": "Invalid session"}, 403)
                    return
                
                fi = session["files"].get(file_id)
                if not fi or fi["token"] != token:
                    self._send_json({"message": "Invalid token"}, 403)
                    return
                
                length = int(self.headers.get("Content-Length", 0))
                chunks = []
                received = 0
                total_files = len(session["files"])
                keys = list(session["files"].keys())
                idx = keys.index(file_id) + 1 if file_id in keys else 0
                fname = fi["name"]
                
                while received < length:
                    chunk = self.rfile.read(min(65536, length - received))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    received += len(chunk)
                    if receiver.on_progress and length > 0:
                        pct = int(received * 100 / length)
                        receiver.on_progress(idx, total_files, f"{fname} ({pct}%)")
                
                file_data = b"".join(chunks)
                safe_name = Path(fname).name
                file_path = receiver.save_dir / safe_name
                
                if file_path.exists():
                    stem, suffix = file_path.stem, file_path.suffix
                    counter = 1
                    while file_path.exists():
                        file_path = receiver.save_dir / f"{stem} ({counter}){suffix}"
                        counter += 1
                
                file_path.write_bytes(file_data)
                
                logger.info(f"接收完成: {safe_name} ({len(file_data)} bytes)")
                
                if receiver.on_file_received:
                    receiver.on_file_received(str(file_path))
                
                self.send_response(200)
                self.end_headers()
            
            def _handle_cancel(self):
                query = {}
                if "?" in self.path:
                    import urllib.parse
                    query = dict(urllib.parse.parse_qsl(self.path.split("?")[1]))
                sid = query.get("sessionId", "")
                if sid in receiver._sessions:
                    del receiver._sessions[sid]
                self.send_response(200)
                self.end_headers()
            
            def _handle_info(self):
                self._send_json({
                    "alias": receiver.alias,
                    "version": PROTOCOL_VERSION,
                    "deviceModel": "Windows",
                    "deviceType": DEVICE_TYPE,
                    "fingerprint": receiver.fingerprint,
                    "port": HTTP_PORT,
                    "protocol": "https",
                    "download": True,
                })
        
        # 创建 HTTPS 服务器
        self._http_server = HTTPServer(("0.0.0.0", HTTP_PORT), LocalSendHandler)
        
        # 用 SSL 包装 socket
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self._cert_file)
        self._http_server.socket = ctx.wrap_socket(
            self._http_server.socket, server_side=True
        )
        
        self._http_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        self._http_thread.start()
    
    # ─── UDP 多播 ───────────────────────────
    
    def _start_udp_multicast(self):
        self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        self._udp_socket.bind(("0.0.0.0", MULTICAST_PORT))
        
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        self._udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        self._udp_thread = threading.Thread(target=self._udp_listen_loop, daemon=True)
        self._udp_thread.start()
    
    def _udp_listen_loop(self):
        while self._running:
            try:
                data, addr = self._udp_socket.recvfrom(4096)
                self._handle_udp_message(data, addr)
            except socket.timeout:
                continue
            except Exception:
                if self._running:
                    pass
    
    def _handle_udp_message(self, data: bytes, addr: tuple):
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        
        if msg.get("fingerprint") == self.fingerprint:
            return
        
        if msg.get("announce") and msg.get("port"):
            self._reply_to_device(addr[0], msg)
    
    def _reply_to_device(self, sender_ip: str, msg: dict):
        protocol = msg.get("protocol", "https")
        try:
            import urllib.request
            body = json.dumps({
                "alias": self.alias,
                "version": PROTOCOL_VERSION,
                "deviceModel": "Windows",
                "deviceType": DEVICE_TYPE,
                "fingerprint": self.fingerprint,
                "port": HTTP_PORT,
                "protocol": "https",
                "download": True,
            }).encode("utf-8")
            
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            url = f"{protocol}://{sender_ip}:{msg['port']}/api/localsend/v2/register"
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3, context=ctx):
                pass
            logger.info(f"回复设备: {msg.get('alias', 'unknown')}")
        except Exception:
            pass
    
    def _send_announcement(self):
        msg = json.dumps({
            "alias": self.alias,
            "version": PROTOCOL_VERSION,
            "deviceModel": "Windows",
            "deviceType": DEVICE_TYPE,
            "fingerprint": self.fingerprint,
            "port": HTTP_PORT,
            "protocol": "https",
            "download": True,
            "announce": True,
        }).encode("utf-8")
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.sendto(msg, (MULTICAST_GROUP, MULTICAST_PORT))
            sock.close()
            logger.info(f"已发送 UDP announcement")
        except Exception as e:
            logger.warning(f"发送 announcement 失败: {e}")
