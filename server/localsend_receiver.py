"""LocalSend HTTPS receiver + HTTP browse server"""

import os, json, uuid, socket, struct, ssl, hashlib, logging, tempfile, threading, datetime
import html, shutil, urllib.parse
from pathlib import Path
from typing import Optional, Callable
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)
MULTICAST_GROUP, MULTICAST_PORT, HTTP_PORT, BROWSE_PORT = "224.0.0.167", 53317, 53317, 8899
PROTOCOL_VERSION, DEVICE_TYPE = "2.0", "desktop"


def _safe_file_link(file_name: str) -> tuple[str, str]:
    """Return an HTML-safe label and a URL-encoded download path."""
    return html.escape(file_name), "/download/" + urllib.parse.quote(file_name, safe="")


def _stream_to_file(source, destination: Path, length: int, on_chunk=None) -> int:
    """Copy exactly ``length`` bytes from a request stream to disk."""
    received = 0
    with open(destination, "wb") as output:
        while received < length:
            chunk = source.read(min(65536, length - received))
            if not chunk:
                break
            output.write(chunk)
            received += len(chunk)
            if on_chunk:
                on_chunk(received)
        output.flush()
        os.fsync(output.fileno())
    if received != length:
        raise EOFError(f"incomplete upload: expected {length}, received {received}")
    return received

class LocalSendReceiver:
    def __init__(self, save_dir: str, alias: str = "MusicSync",
                 on_file_received: Optional[Callable] = None,
                 on_progress: Optional[Callable] = None):
        self.save_dir = Path(save_dir); self.alias = alias
        self.on_file_received = on_file_received; self.on_progress = on_progress
        self.fingerprint = ""; self._cert_file = None
        self._http_server = None; self._browse_server = None
        self._udp_socket = None; self._running = False; self._sessions = {}

    @property
    def is_running(self): return self._running

    def start(self):
        if self._running: return
        self.save_dir.mkdir(parents=True, exist_ok=True); self._running = True
        self._generate_cert(); self._start_https_server(); self._start_browse_server()
        try: self._start_udp_multicast(); self._send_announcement()
        except Exception as e: logger.warning(f"UDP failed: {e}")
        logger.info(f"LocalSend: {self.alias} @ {self._get_local_ip()}:{HTTP_PORT}")

    def stop(self):
        self._running = False
        if self._http_server: self._http_server.shutdown()
        if self._browse_server: self._browse_server.shutdown()
        if self._udp_socket: self._udp_socket.close()
        if self._cert_file and os.path.exists(self._cert_file):
            try: os.unlink(self._cert_file)
            except: pass
        logger.info("LocalSend stopped")

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]; s.close(); return ip
        except: return "127.0.0.1"

    def _generate_cert(self):
        from cryptography import x509; from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(65537, 2048)
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MusicSync")])
        cert = x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(
            key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
            datetime.datetime.utcnow()).not_valid_after(datetime.datetime.utcnow() +
            datetime.timedelta(days=3650)).sign(key, hashes.SHA256())
        cp, kp = cert.public_bytes(serialization.Encoding.PEM), key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False); tmp.write(cp + kp); tmp.close()
        self._cert_file = tmp.name; self.fingerprint = hashlib.sha256(cp).hexdigest()
        logger.info("HTTPS cert generated")

    def _start_https_server(self):
        r = self
        class H(BaseHTTPRequestHandler):
            def log_message(s, *a): pass
            def _json(s, d, st=200):
                b = json.dumps(d, ensure_ascii=False).encode()
                s.send_response(st); s.send_header("Content-Type", "application/json")
                s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
            def _read(s):
                n = int(s.headers.get("Content-Length", 0))
                return json.loads(s.rfile.read(n)) if n else {}
            def do_POST(s):
                p = s.path.split("?")[0]
                if p == "/api/localsend/v2/register": s._reg()
                elif p == "/api/localsend/v2/prepare-upload": s._prep()
                elif p == "/api/localsend/v2/upload": s._up()
                elif p == "/api/localsend/v2/cancel": s._cancel()
                else: s._json({"message":"not found"}, 404)
            def do_GET(s):
                if s.path.split("?")[0] == "/api/localsend/v2/info": s._info()
                else: s._json({"message":"not found"}, 404)
            def _reg(s):
                d = {}; 
                try: d = s._read()
                except: pass
                logger.info(f"register: {d.get('alias','?')}")
                s._json({"alias":r.alias,"version":PROTOCOL_VERSION,"deviceModel":"Windows",
                    "deviceType":DEVICE_TYPE,"fingerprint":r.fingerprint,"port":HTTP_PORT,
                    "protocol":"https","download":True})
            def _prep(s):
                try: d = s._read()
                except: s._json({"message":"Invalid"},400); return
                fs, sid, tokens, skipped = d.get("files",{}), uuid.uuid4().hex[:12], {}, 0
                sf = {}
                for fid, inf in fs.items():
                    nm, sz = inf.get("fileName","?"), inf.get("size",0)
                    ex = r.save_dir / Path(nm).name
                    if ex.exists() and ex.stat().st_size == sz: skipped += 1; continue
                    tk = uuid.uuid4().hex[:16]; tokens[fid] = tk
                    sf[fid] = {"name":nm,"size":sz,"token":tk}
                if skipped: logger.info(f"skip {skipped} dups")
                if not sf: s.send_response(204); s.end_headers(); return
                r._sessions[sid] = {"files":sf,"sender":d.get("info",{}).get("alias","?")}
                logger.info(f"upload: {len(sf)} files, sid={sid}")
                s._json({"sessionId":sid,"files":tokens})
            def _up(s):
                import urllib.parse; q = dict(urllib.parse.parse_qsl(s.path.split("?")[1])) if "?" in s.path else {}
                sid, fid, tok = q.get("sessionId",""), q.get("fileId",""), q.get("token","")
                se = r._sessions.get(sid)
                if not se: s._json({"message":"bad session"},403); return
                fi = se["files"].get(fid)
                if not fi or fi["token"] != tok: s._json({"message":"bad token"},403); return
                length = int(s.headers.get("Content-Length",0))
                if length <= 0 or (fi["size"] and length != fi["size"]):
                    s._json({"message":"size mismatch"},400); return
                if shutil.disk_usage(r.save_dir).free < length:
                    s._json({"message":"insufficient storage"},507); return
                total, keys = len(se["files"]), list(se["files"].keys())
                idx = keys.index(fid)+1 if fid in keys else 0; fn = fi["name"]
                safe = Path(fn).name; fp = r.save_dir / safe
                if fp.exists():
                    st, su = fp.stem, fp.suffix; c = 1
                    while fp.exists(): fp = r.save_dir / f"{st} ({c}){su}"; c += 1
                temp_handle = tempfile.NamedTemporaryFile(
                    prefix=".echovault-upload-", suffix=".part", dir=r.save_dir, delete=False
                )
                temp_path = Path(temp_handle.name); temp_handle.close()

                def report_progress(recv):
                    if r.on_progress and length > 0:
                        r.on_progress(idx, total, f"{fn} ({int(recv*100/length)}%)")

                try:
                    received = _stream_to_file(s.rfile, temp_path, length, report_progress)
                    os.replace(temp_path, fp)
                except EOFError as exc:
                    if temp_path.exists(): temp_path.unlink()
                    logger.warning(str(exc)); s._json({"message":"incomplete upload"},400); return
                except OSError as exc:
                    if temp_path.exists(): temp_path.unlink()
                    logger.error(f"upload failed: {exc}"); s._json({"message":"write failed"},500); return
                logger.info(f"received: {safe} ({received}B)")
                if r.on_file_received: r.on_file_received(str(fp))
                s.send_response(200); s.end_headers()
            def _cancel(s):
                import urllib.parse; q = dict(urllib.parse.parse_qsl(s.path.split("?")[1])) if "?" in s.path else {}
                sid = q.get("sessionId","")
                if sid in r._sessions: del r._sessions[sid]
                s.send_response(200); s.end_headers()
            def _info(s):
                s._json({"alias":r.alias,"version":PROTOCOL_VERSION,"deviceModel":"Windows",
                    "deviceType":DEVICE_TYPE,"fingerprint":r.fingerprint,"port":HTTP_PORT,
                    "protocol":"https","download":True})
        self._http_server = HTTPServer(("0.0.0.0", HTTP_PORT), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(self._cert_file)
        self._http_server.socket = ctx.wrap_socket(self._http_server.socket, server_side=True)
        threading.Thread(target=self._http_server.serve_forever, daemon=True).start()

    def _start_browse_server(self):
        r = self
        class B(BaseHTTPRequestHandler):
            def log_message(s, *a): pass
            def do_GET(s):
                p = s.path.split("?")[0]
                if p == "/" or p == "/index.html": s._idx()
                elif p.startswith("/download/"): s._dl(p[10:])
                else: s.send_response(404); s.end_headers()
            def _idx(s):
                ip = r._get_local_ip(); items = ""
                if r.save_dir.exists():
                    for f in sorted(r.save_dir.iterdir()):
                        if f.is_file():
                            sz = f"{f.stat().st_size/1024:.0f}KB" if f.stat().st_size>1024 else f"{f.stat().st_size}B"
                            label, href = _safe_file_link(f.name)
                            items += f'<li><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{label}</span><span style="color:#888;font-size:12px;margin:0 12px">{sz}</span><a style="color:#1976D2;text-decoration:none;font-size:13px" href="{href}">下载</a></li>'
                html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MusicSync</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,sans-serif;background:#f5f5f5;color:#333}}
.h{{background:#1976D2;color:#fff;padding:16px}}.h h1{{font-size:20px;font-weight:500}}.h p{{font-size:13px;opacity:.85;margin-top:4px}}
.c{{max-width:600px;margin:16px auto;padding:0 12px}}.card{{background:#fff;border-radius:8px;padding:16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.card h2{{font-size:15px;margin-bottom:8px;color:#1976D2}}ul{{list-style:none}}
li{{display:flex;align-items:center;padding:10px 0;border-bottom:1px solid #eee;font-size:14px}}li:last-child{{border-bottom:none}}
</style></head><body><div class="h"><h1>MusicSync</h1><p>{r.alias} @ {ip}:{BROWSE_PORT}</p></div>
<div class="c"><div class="card"><h2>电脑上的文件</h2><ul>{items or '<li style="color:#999">暂无文件</li>'}</ul></div>
<div class="card"><h2>发送到电脑</h2><p style="font-size:13px;color:#666;line-height:1.8">打开手机 LocalSend App，找到 <b>{r.alias}</b> 设备，选择文件发送。</p></div>
</div></body></html>"""
                s.send_response(200); s.send_header("Content-Type","text/html; charset=utf-8"); s.end_headers()
                s.wfile.write(html.encode())
            def _dl(s, fn):
                decoded_name = urllib.parse.unquote(fn)
                fp = r.save_dir / Path(decoded_name).name
                if not fp.exists(): s.send_response(404); s.end_headers(); return
                s.send_response(200)
                s.send_header("Content-Type","application/octet-stream")
                quoted_name = urllib.parse.quote(fp.name, safe="")
                s.send_header("Content-Disposition",f"attachment; filename*=UTF-8''{quoted_name}")
                s.send_header("Content-Length",str(fp.stat().st_size)); s.end_headers()
                with open(fp, "rb") as source:
                    for chunk in iter(lambda: source.read(65536), b""):
                        s.wfile.write(chunk)
        self._browse_server = HTTPServer(("0.0.0.0", BROWSE_PORT), B)
        threading.Thread(target=self._browse_server.serve_forever, daemon=True).start()
        logger.info(f"Browse: http://{self._get_local_ip()}:{BROWSE_PORT}")

    def _start_udp_multicast(self):
        self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"): self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._udp_socket.bind(("0.0.0.0", MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        self._udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self._running:
            try: d, a = self._udp_socket.recvfrom(4096); self._on_udp(d, a)
            except: pass

    def _on_udp(self, data, addr):
        try: m = json.loads(data.decode())
        except: return
        if m.get("fingerprint") == self.fingerprint: return
        if m.get("announce") and m.get("port"): self._reply(addr[0], m)

    def _reply(self, ip, msg):
        try:
            import urllib.request; b = json.dumps({"alias":self.alias,"version":PROTOCOL_VERSION,
                "deviceModel":"Windows","deviceType":DEVICE_TYPE,"fingerprint":self.fingerprint,
                "port":HTTP_PORT,"protocol":"https","download":True}).encode()
            ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
            u = f"{msg.get('protocol','https')}://{ip}:{msg['port']}/api/localsend/v2/register"
            urllib.request.urlopen(urllib.request.Request(u, data=b, headers={"Content-Type":"application/json"}, method="POST"), timeout=3, context=ctx)
        except: pass

    def _send_announcement(self):
        try:
            m = json.dumps({"alias":self.alias,"version":PROTOCOL_VERSION,"deviceModel":"Windows",
                "deviceType":DEVICE_TYPE,"fingerprint":self.fingerprint,"port":HTTP_PORT,
                "protocol":"https","download":True,"announce":True}).encode()
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.sendto(m, (MULTICAST_GROUP, MULTICAST_PORT)); s.close()
        except Exception as e: logger.warning(f"announce failed: {e}")
