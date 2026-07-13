"""
局域网 HTTP 文件传输服务

基于 aiohttp，提供:
- 文件下载端点
- 文件列表 API
- 简单 Web 管理页面（手机浏览器访问）

手机端通过浏览器访问 http://电脑IP:8899 即可:
- 查看差异文件列表
- 下载缺失的文件
- 浏览音乐库
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from aiohttp import web
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False
    web = None


def resolve_library_path(root_dir: str | Path, requested_path: str) -> Path:
    """Resolve a requested path and ensure it remains inside the library root."""
    root = Path(root_dir).expanduser().resolve()
    candidate = (root / requested_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("requested path is outside the music library") from exc
    return candidate


class SyncHTTPServer:
    """文件同步 HTTP 服务"""
    
    DEFAULT_PORT = 8899
    
    def __init__(self, music_dir: str, port: int = DEFAULT_PORT):
        if not _HAS_AIOHTTP:
            raise RuntimeError("aiohttp 未安装。请运行: pip install aiohttp")
        
        self.music_dir = str(Path(music_dir).expanduser().resolve())
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
    
    async def start(self):
        """启动 HTTP 服务"""
        self._app = web.Application()
        self._setup_routes()
        
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        
        logger.info(f"HTTP 文件服务已启动: http://0.0.0.0:{self.port}")
    
    async def stop(self):
        """停止 HTTP 服务"""
        if self._runner:
            await self._runner.cleanup()
            logger.info("HTTP 文件服务已停止")
    
    def _setup_routes(self):
        """设置路由"""
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/files", self._handle_list_files)
        self._app.router.add_get("/download/{path:.*}", self._handle_download)
    
    async def _handle_index(self, request: web.Request) -> web.Response:
        """首页 — 简单 Web 管理页面"""
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MusicSync</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #1976D2; color: white; padding: 16px 20px; }
  .header h1 { font-size: 20px; font-weight: 500; }
  .header p { font-size: 13px; opacity: 0.85; margin-top: 4px; }
  .container { max-width: 800px; margin: 20px auto; padding: 0 16px; }
  .card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .card h2 { font-size: 16px; margin-bottom: 12px; color: #1976D2; }
  .btn { display: inline-block; padding: 10px 20px; background: #1976D2; color: white; border: none; border-radius: 4px; font-size: 14px; cursor: pointer; text-decoration: none; }
  .file-list { list-style: none; }
  .file-list li { padding: 8px 0; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }
  .file-list li:last-child { border-bottom: none; }
  .file-name { font-size: 14px; }
  .file-size { font-size: 12px; color: #888; }
  .download-link { color: #1976D2; text-decoration: none; font-size: 13px; }
</style>
</head>
<body>
<div class="header">
  <h1>MusicSync</h1>
  <p>手机端文件同步 — 在电脑端 MusicSync 应用中管理同步</p>
</div>
<div class="container">
  <div class="card">
    <h2>操作</h2>
    <p style="margin-bottom:12px;color:#666;font-size:14px;">请在电脑端 MusicSync 应用中执行同步比对操作。本页面仅供查看和下载文件。</p>
    <a href="/api/files" class="btn">查看文件列表</a>
  </div>
  <div class="card">
    <h2>使用说明</h2>
    <p style="font-size:14px;color:#666;line-height:1.8;">
      1. 在电脑端打开 MusicSync<br>
      2. 切换到"同步"面板<br>
      3. 配置手机端文件夹路径<br>
      4. 点击"对比"查看差异<br>
      5. 点击"同步"执行文件传输
    </p>
  </div>
</div>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html; charset=utf-8")
    
    async def _handle_list_files(self, request: web.Request) -> web.Response:
        """列出音乐目录中的文件"""
        files = []
        root = Path(self.music_dir)
        
        if root.exists():
            for entry in sorted(root.rglob("*")):
                if entry.is_file():
                    rel = str(entry.relative_to(root)).replace("\\", "/")
                    stat = entry.stat()
                    files.append({
                        "name": rel,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
        
        return web.json_response({
            "root": root.name,
            "count": len(files),
            "files": files[:500],  # 限制数量
        })
    
    async def _handle_download(self, request: web.Request) -> web.Response:
        """下载文件"""
        file_path = request.match_info.get("path", "")
        try:
            full_path = resolve_library_path(self.music_dir, file_path)
        except ValueError:
            raise web.HTTPForbidden()
        
        if not full_path.is_file():
            raise web.HTTPNotFound()
        
        return web.FileResponse(full_path)
