"""
LocalSend 协议接收端

实现 LocalSend Protocol v2.1，让 MusicSync 在局域网中
作为一个 LocalSend 设备出现。手机端的 LocalSend App
可以直接发现本机并将音乐文件发送到指定文件夹。

协议详情: https://github.com/localsend/protocol

流程:
1. 本机加入 UDP 多播组 224.0.0.167:53317
2. 发送 announcement，声明自己是 "desktop" 设备
3. 监听其他设备的 announcement，收到后回复 HTTP register
4. 启动 HTTP 服务器 (端口 53317)，处理文件上传
"""

import os
import json
import uuid
import socket
import struct
import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional, Callable
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

# LocalSend 协议常量
MULTICAST_GROUP = "224.0.0.167"
MULTICAST_PORT = 53317
HTTP_PORT = 53317
PROTOCOL_VERSION = "2.0"
DEVICE_TYPE = "desktop"


class LocalSendReceiver:
    """LocalSend 协议接收端
    
    在局域网中模拟一个 LocalSend 设备，接收其他设备发送的文件。
    """
    
    def __init__(
        self,
        save_dir: str,
        alias: str = "MusicSync",
        on_file_received: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
    ):
        """
        Args:
            save_dir: 接收文件的保存目录
            alias: 在 LocalSend 中显示的名称
            on_file_received: 文件接收完成回调 (file_path: str)
            on_progress: 传输进度回调 (current: int, total: int, filename: str)
        """
        self.save_dir = Path(save_dir)
        self.alias = alias
        self.on_file_received = on_file_received
        self.on_progress = on_progress
        self.fingerprint = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        
        self._http_server: Optional[HTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._udp_socket: Optional[socket.socket] = None
        self._udp_thread: Optional[threading.Thread] = None
        self._running = False
        
        # 当前上传会话 {sessionId: {"files": {fileId: {"name", "size", "token"}}}}
        self._sessions: dict = {}
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def start(self):
        """启动 LocalSend 接收端（UDP 多播 + HTTP 服务器）"""
        if self._running:
            return
        
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        
        # 启动 HTTP 服务器
        self._start_http_server()
        
        # 启动 UDP 多播（可选，失败不影响 HTTP 接收）
        try:
            self._start_udp_multicast()
            self._send_announcement()
        except Exception as e:
            logger.warning(f"UDP 多播启动失败（不影响 HTTP 接收功能）: {e}")
        
        ip = self._get_local_ip()
        logger.info(f"LocalSend 接收端已启动: {self.alias} @ {ip}:{HTTP_PORT}")
    
    def stop(self):
        """停止接收端"""
        self._running = False
        
        if self._http_server:
            self._http_server.shutdown()
        if self._udp_socket:
            self._udp_socket.close()
        
        logger.info("LocalSend 接收端已停止")
    
    def _get_local_ip(self) -> str:
        """获取本机局域网 IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    # ─── HTTP 服务器 ───────────────────────
    
    def _start_http_server(self):
        """启动 HTTP 服务器处理 LocalSend API"""
        receiver = self  # 闭包引用
        
        class LocalSendHandler(BaseHTTPRequestHandler):
            
            def log_message(self, format, *args):
                logger.debug(f"LocalSend HTTP: {args}")
            
            def _send_json(self, data: dict, status: int = 200):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            
            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    return {}
                body = self.rfile.read(length)
                return json.loads(body)
            
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
                path = self.path.split("?")[0]
                if path == "/api/localsend/v2/info":
                    self._handle_info()
                else:
                    self._send_json({"message": "not found"}, 404)
            
            def _handle_register(self):
                """其他设备发来的注册请求，回复我们的设备信息"""
                try:
                    data = self._read_json()
                    logger.info(f"设备注册请求: {data.get('alias', 'unknown')}")
                except Exception:
                    pass
                
                self._send_json({
                    "alias": receiver.alias,
                    "version": PROTOCOL_VERSION,
                    "deviceModel": "Windows",
                    "deviceType": DEVICE_TYPE,
                    "fingerprint": receiver.fingerprint,
                    "download": True,
                })
            
            def _handle_prepare_upload(self):
                """发送方准备上传文件，返回 sessionId 和 file token"""
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
                    
                    # 检查是否已存在相同文件（名称+大小一致则跳过）
                    existing_path = receiver.save_dir / Path(name).name
                    if existing_path.exists() and existing_path.stat().st_size == size:
                        logger.info(f"跳过重复文件: {name} (已存在且大小相同)")
                        skipped += 1
                        continue
                    
                    token = uuid.uuid4().hex[:16]
                    file_tokens[file_id] = token
                    session_files[file_id] = {
                        "name": name,
                        "size": size,
                        "token": token,
                    }
                
                if skipped > 0:
                    logger.info(f"跳过 {skipped} 个重复文件")
                
                if not session_files:
                    # 全部跳过
                    logger.info(f"所有文件均已存在，无需传输")
                    self.send_response(204)  # No Content
                    self.end_headers()
                    return
                
                receiver._sessions[session_id] = {
                    "files": session_files,
                    "sender": sender_alias,
                }
                
                logger.info(
                    f"收到上传请求: {sender_alias}, "
                    f"{len(files_info)} 个文件, session={session_id}"
                )
                
                self._send_json({
                    "sessionId": session_id,
                    "files": file_tokens,
                })
            
            def _handle_upload(self):
                """接收文件二进制数据"""
                # 解析查询参数
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
                
                file_info = session["files"].get(file_id)
                if not file_info or file_info["token"] != token:
                    self._send_json({"message": "Invalid token"}, 403)
                    return
                
                # 读取文件内容（分块 + 进度回调）
                length = int(self.headers.get("Content-Length", 0))
                chunks = []
                received = 0
                chunk_size = 65536
                filename = file_info["name"]
                
                total_files = len(session["files"])
                keys = list(session["files"].keys())
                current_idx = keys.index(file_id) + 1 if file_id in keys else 0
                
                while received < length:
                    chunk = self.rfile.read(min(chunk_size, length - received))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    received += len(chunk)
                    
                    if receiver.on_progress and length > 0:
                        pct = int(received * 100 / length)
                        receiver.on_progress(current_idx, total_files, f"{filename} ({pct}%)")
                
                file_data = b"".join(chunks)
                # 保存文件
                filename = file_info["name"]
                safe_name = Path(filename).name  # 防止路径遍历
                file_path = receiver.save_dir / safe_name
                
                # 处理重名
                if file_path.exists():
                    stem = file_path.stem
                    suffix = file_path.suffix
                    counter = 1
                    while file_path.exists():
                        file_path = receiver.save_dir / f"{stem} ({counter}){suffix}"
                        counter += 1
                
                file_path.write_bytes(file_data)
                
                logger.info(
                    f"接收完成: {safe_name} ({len(file_data)} bytes) "
                    f"来自 {session['sender']}"
                )
                
                # 回调
                if receiver.on_file_received:
                    receiver.on_file_received(str(file_path))
                
                self.send_response(200)
                self.end_headers()
            
            def _handle_cancel(self):
                """取消会话"""
                query = {}
                if "?" in self.path:
                    import urllib.parse
                    query = dict(urllib.parse.parse_qsl(self.path.split("?")[1]))
                
                session_id = query.get("sessionId", "")
                if session_id in receiver._sessions:
                    del receiver._sessions[session_id]
                    logger.info(f"会话已取消: {session_id}")
                
                self.send_response(200)
                self.end_headers()
            
            def _handle_info(self):
                """返回设备信息（调试用）"""
                self._send_json({
                    "alias": receiver.alias,
                    "version": PROTOCOL_VERSION,
                    "deviceModel": "Windows",
                    "deviceType": DEVICE_TYPE,
                    "fingerprint": receiver.fingerprint,
                    "download": True,
                })
        
        self._http_server = HTTPServer(("0.0.0.0", HTTP_PORT), LocalSendHandler)
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever, daemon=True
        )
        self._http_thread.start()
    
    # ─── UDP 多播 ───────────────────────────
    
    def _start_udp_multicast(self):
        """加入 UDP 多播组，监听其他设备的 announcement"""
        self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT 仅 Linux/macOS 支持，Windows 跳过
        if hasattr(socket, "SO_REUSEPORT"):
            self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        # 绑定端口
        self._udp_socket.bind(("0.0.0.0", MULTICAST_PORT))
        
        # 加入多播组
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        self._udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        self._udp_thread = threading.Thread(target=self._udp_listen_loop, daemon=True)
        self._udp_thread.start()
    
    def _udp_listen_loop(self):
        """UDP 多播监听循环"""
        while self._running:
            try:
                data, addr = self._udp_socket.recvfrom(4096)
                self._handle_udp_message(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.debug(f"UDP 错误: {e}")
    
    def _handle_udp_message(self, data: bytes, addr: tuple):
        """处理收到的 UDP 多播消息"""
        try:
            msg = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        
        # 忽略自己的消息
        if msg.get("fingerprint") == self.fingerprint:
            return
        
        # 如果对方发了 announcement 且 announce=true，回复我们的信息
        if msg.get("announce") and msg.get("port"):
            sender_ip = addr[0]
            sender_port = msg["port"]
            protocol = msg.get("protocol", "http")
            
            # 通过 HTTP 发送 register 请求
            try:
                import urllib.request
                register_data = json.dumps({
                    "alias": self.alias,
                    "version": PROTOCOL_VERSION,
                    "deviceModel": "Windows",
                    "deviceType": DEVICE_TYPE,
                    "fingerprint": self.fingerprint,
                    "port": HTTP_PORT,
                    "protocol": "http",
                    "download": True,
                }).encode("utf-8")
                
                url = f"{protocol}://{sender_ip}:{sender_port}/api/localsend/v2/register"
                req = urllib.request.Request(
                    url, data=register_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                # 忽略证书错误（LocalSend 用自签名证书）
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(req, timeout=2, context=ctx) as resp:
                    pass
                
                logger.info(f"已回复设备: {msg.get('alias', 'unknown')} @ {sender_ip}")
            except Exception as e:
                logger.debug(f"回复设备失败: {e}")
    
    def _send_announcement(self):
        """发送 UDP 多播 announcement，让其他设备发现我们"""
        msg = json.dumps({
            "alias": self.alias,
            "version": PROTOCOL_VERSION,
            "deviceModel": "Windows",
            "deviceType": DEVICE_TYPE,
            "fingerprint": self.fingerprint,
            "port": HTTP_PORT,
            "protocol": "http",
            "download": True,
            "announce": True,
        }).encode("utf-8")
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.sendto(msg, (MULTICAST_GROUP, MULTICAST_PORT))
            sock.close()
            logger.info(f"已发送 UDP announcement: {self.alias}")
        except Exception as e:
            logger.warning(f"发送 announcement 失败: {e}")
