"""设置对话框"""
import os, subprocess, sys, hashlib
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QCheckBox, QPushButton,
    QGroupBox, QLabel, QDialogButtonBox, QFileDialog, QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from core.config import AppConfig, config_manager


# Whisper 模型下载 URL (OpenAI 官方 + 各镜像)
_GH_RELEASE = "https://github.com/xiaohaifale-QWQ/echovault-models/releases/download/v1.0"


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_model_sha256(model: str) -> str:
    """Extract the expected digest embedded in OpenAI Whisper's model URL."""
    try:
        import whisper
        url = whisper._MODELS[model]
    except (ImportError, KeyError):
        return ""
    parts = url.rstrip("/").split("/")
    return parts[-2] if len(parts) >= 2 and len(parts[-2]) == 64 else ""

class _GPUDetectWorker(QThread):
    """后台扫描显卡"""
    result_ready = pyqtSignal(str)  # GPU 名称 或 错误信息
    
    def run(self):
        try:
            # 先试 nvidia-smi
            import subprocess as sp
            r = sp.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                       capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                name = r.stdout.strip().split("\n")[0].strip()
                self.result_ready.emit(f"✅ {name}")
                return
        except Exception:
            pass
        
        # 回退：检查 torch.cuda
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                self.result_ready.emit(f"✅ {name} (CUDA 已就绪)")
                return
        except ImportError:
            pass
        
        self.result_ready.emit("❌ 未检测到 NVIDIA 显卡")


class _GPUInstallWorker(QThread):
    """后台安装 PyTorch CUDA 版本 — 双源 + 可取消"""
    progress = pyqtSignal(int, str)  # percent, message
    finished = pyqtSignal(bool, str)
    
    def __init__(self):
        super().__init__()
        self._cancelled = False
        self._proc = None
    
    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self._proc:
            try: self._proc.terminate()
            except: pass
    
    def run(self):
        try:
            import re
            self.progress.emit(0, "正在解析 PyTorch CUDA 12.1 依赖...")
            
            # 只用 PyTorch CDN（不用清华镜像，它会优先给 CPU 版 torch）
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio",
                 "--index-url", "https://download.pytorch.org/whl/cu121"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True,
            )
            
            pkg_name = ""
            for line in iter(self._proc.stdout.readline, ""):
                if self._cancelled or self.isInterruptionRequested():
                    self._proc.terminate()
                    self.finished.emit(False, "安装已取消")
                    return
                line = line.strip()
                if not line:
                    continue
                
                # "Downloading <url> (<size>)"
                m = re.search(r'Downloading\s+(\S+)\s+\(([\d.]+\s*\w+)\)', line)
                if m:
                    pkg_name = m.group(1).split("/")[-1][:50]
                    size_str = m.group(2)
                    self.progress.emit(0, f"⬇ {pkg_name} ({size_str})")
                    continue
                
                # " 1.2/2.5 GB 5.2 MB/s eta 0:04:01"
                m2 = re.search(r'(\d+\.?\d*)\s*/\s*(\d+\.?\d*)\s*(\w+)', line)
                if m2:
                    try:
                        done = float(m2.group(1))
                        total = float(m2.group(2))
                        pct = int(done / total * 100) if total > 0 else 0
                        speed_match = re.search(r'(\d+\.?\d*\s*\w+/s)', line)
                        speed = speed_match.group(1) if speed_match else ""
                        self.progress.emit(pct, f"⬇ {pkg_name} — {speed} ({pct}%)")
                    except: pass
                    continue
                
                # pip 百分比: "━━━━━ 45%"
                m3 = re.search(r'(\d+)%', line)
                if m3 and pkg_name:
                    pct = int(m3.group(1))
                    speed_match = re.search(r'(\d+\.?\d*\s*\w+/s)', line)
                    speed = speed_match.group(1) if speed_match else ""
                    self.progress.emit(pct, f"⬇ {pkg_name} — {speed} ({pct}%)")
                    continue
                
                if "already satisfied" in line.lower():
                    self.progress.emit(100, "已安装，跳过")
                elif any(kw in line.lower() for kw in ['installing', 'successfully installed', 'collecting']):
                    self.progress.emit(-1, line[:100])
            
            self._proc.wait()
            if self._cancelled or self.isInterruptionRequested():
                self.finished.emit(False, "安装已取消")
                return
            if self._proc.returncode == 0:
                self.finished.emit(True, "GPU 加速安装完成！重启后生效。")
            else:
                self.finished.emit(False, f"pip 返回错误码 {self._proc.returncode}\n请重试或检查网络")
        except FileNotFoundError:
            self.finished.emit(False, "找不到 pip，请确认 Python 安装正确")
        except Exception as e:
            self.finished.emit(False, str(e))


class _DownloadWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, model: str):
        super().__init__(); self.model = model; self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        import os as _os
        try:
            try: import whisper
            except ImportError:
                self.progress.emit(0, "安装 openai-whisper...")
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", "openai-whisper", "-q",
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                    "--trusted-host", "pypi.tuna.tsinghua.edu.cn"
                ])

            cache = _os.path.join(_os.path.expanduser("~"), ".cache", "whisper")
            model_file = _os.path.join(cache, f"{self.model}.pt")
            
            expected_hash = _official_model_sha256(self.model)
            if _os.path.exists(model_file) and _os.path.getsize(model_file) > 100000:
                if not expected_hash or _file_sha256(model_file) == expected_hash:
                    self.finished.emit(True, f"{self.model} 模型已缓存")
                    return
                _os.remove(model_file)

            _os.makedirs(cache, exist_ok=True)
            
            if self._cancelled or self.isInterruptionRequested():
                self.finished.emit(False, "下载已取消")
                return

            if self.model == "medium":
                ok = self._download_medium(cache)
            else:
                url = f"{_GH_RELEASE}/{self.model}.pt"
                ok = self._download_file(url, model_file)
            
            if self._cancelled or self.isInterruptionRequested():
                self.finished.emit(False, "下载已取消")
                return

            if not ok:
                self.finished.emit(False, "下载失败, 请检查网络")
                return

            if expected_hash and _file_sha256(model_file) != expected_hash:
                _os.remove(model_file)
                self.finished.emit(False, "模型 SHA-256 校验失败，请重新下载")
                return
            
            self.finished.emit(True, f"{self.model} 模型下载完成")

        except subprocess.CalledProcessError:
            self.finished.emit(False, "pip 安装失败")
        except Exception as e:
            self.finished.emit(False, str(e))

    def _download_medium(self, cache):
        p1_url = f"{_GH_RELEASE}/medium.part1"
        p2_url = f"{_GH_RELEASE}/medium.part2"
        p1_file = os.path.join(cache, "medium.part1")
        p2_file = os.path.join(cache, "medium.part2")
        model_file = os.path.join(cache, "medium.pt")
        import os as _os
        
        if not _os.path.exists(p1_file) or _os.path.getsize(p1_file) < 100000:
            self.progress.emit(0, "下载 medium 分片 1/2...")
            if not self._download_file(p1_url, p1_file):
                return False
        if not _os.path.exists(p2_file) or _os.path.getsize(p2_file) < 100000:
            self.progress.emit(50, "下载 medium 分片 2/2...")
            if not self._download_file(p2_url, p2_file):
                return False
        
        self.progress.emit(95, "合并分片...")
        with open(model_file, "wb") as out:
            for p in [p1_file, p2_file]:
                with open(p, "rb") as inp:
                    while True:
                        chunk = inp.read(1048576)
                        if not chunk: break
                        out.write(chunk)
        _os.remove(p1_file); _os.remove(p2_file)
        return True

    def _download_file(self, url, save_path):
        import urllib.request, socket
        socket.setdefaulttimeout(30)
        partial_path = save_path + ".part"
        try:
            for attempt in range(5):
                try:
                    existing = os.path.getsize(partial_path) if os.path.exists(partial_path) else 0
                    headers = {"User-Agent": "Echovault/1.0"}
                    if existing:
                        headers["Range"] = f"bytes={existing}-"
                    req = urllib.request.Request(url, headers=headers)
                    resp = urllib.request.urlopen(req, timeout=60)
                    break
                except Exception as e:
                    if attempt == 4: raise
                    wait = 2 ** attempt
                    self.progress.emit(0, f"重试 {attempt+2}/5 (等待{wait}s)...")
                    import time; time.sleep(wait)
            resumed = existing > 0 and getattr(resp, "status", 200) == 206
            if not resumed:
                existing = 0
            content_length = int(resp.headers.get("Content-Length", 0))
            total = existing + content_length if content_length else 0
            received = existing
            import time as _time; start = _time.time()
            mode = "ab" if resumed else "wb"
            with open(partial_path, mode) as f:
                while True:
                    if self._cancelled or self.isInterruptionRequested():
                        raise InterruptedError("用户取消")
                    chunk = resp.read(131072)
                    if not chunk: break
                    f.write(chunk); received += len(chunk)
                    if total > 0:
                        elapsed = _time.time() - start
                        speed = received / elapsed if elapsed > 0 else 0
                        pct = int(received * 100 / total)
                        mb_done = received / 1048576
                        mb_total = total / 1048576
                        mb_remain = mb_total - mb_done
                        eta = mb_remain / (speed / 1048576) if speed > 0 else 0
                        if speed > 1048576:
                            speed_str = f"{speed/1048576:.1f} MB/s"
                        else:
                            speed_str = f"{speed/1024:.0f} KB/s"
                        eta_str = f" 剩余 {eta:.0f}s" if eta < 120 else f" 剩余 {eta/60:.1f}min"
                        self.progress.emit(pct, f"{speed_str} | {mb_done:.1f}/{mb_total:.1f} MB ({pct}%){eta_str}")
            if total > 0 and received < total:
                self.progress.emit(99, f"下载不完整 ({received/1048576:.0f}/{total/1048576:.0f}MB), 重试中...")
                return False
            os.replace(partial_path, save_path); return True
        except Exception:
            # 保留 .part 文件，下一次下载可继续。
            return False


class SettingsDialog(QDialog):
    restart_requested = pyqtSignal()  # GPU 安装完成后请求重启
    
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent); self.config = config
        self._setup_ui(); self._load_config()

    def _setup_ui(self):
        self.setWindowTitle("偏好设置"); self.setMinimumWidth(500)
        l = QVBoxLayout(self)

        ag = QGroupBox("语音识别 (ASR)"); af = QFormLayout(ag)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("云端", "groq")
        self.provider_combo.addItem("本地", "local")
        self.provider_combo.currentIndexChanged.connect(self._on_prov)
        af.addRow("识别引擎:", self.provider_combo)

        self.api_input = QLineEdit(); self.api_input.setPlaceholderText("输入 API Key...")
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password); af.addRow("Groq Key:", self.api_input)
        kh = QLabel('<a href="https://console.groq.com/keys" style="color:#1976D2">免费获取 Groq Key</a>')
        kh.setOpenExternalLinks(True); kh.setStyleSheet("font-size:11px"); af.addRow("", kh)
        key_notice = QLabel("Key 将以明文保存在当前用户的本机配置中")
        key_notice.setStyleSheet("font-size:10px;color:#888")
        af.addRow("", key_notice)

        # 保留字段以兼容已有配置，讯飞 Provider 实现前不在界面中展示。
        self.xunfei_input = QLineEdit()
        self.xunfei_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.lang_combo = QComboBox()
        for t, v in [("自动检测", None), ("中文", "zh"), ("英语", "en"), ("日语", "ja"), ("韩语", "ko")]:
            self.lang_combo.addItem(t, v)
        af.addRow("默认语言:", self.lang_combo)

        self.model_combo = QComboBox()
        for t, v in [("tiny (~144 MB, 最快)", "tiny"), ("base (~277 MB, 推荐)", "base"), ("small (~922 MB)", "small"), ("medium (~2.9 GB, 更准)", "medium")]:
            self.model_combo.addItem(t, v)
        self.model_combo.setVisible(False); af.addRow("本地模型:", self.model_combo)

        # 下载按钮行
        dl_btn_row = QHBoxLayout()
        self.btn_dl = QPushButton("下载模型"); self.btn_dl.setVisible(False)
        self.btn_dl.clicked.connect(self._on_download); dl_btn_row.addWidget(self.btn_dl)
        self.btn_cancel_dl = QPushButton("取消下载"); self.btn_cancel_dl.setVisible(False)
        self.btn_cancel_dl.setStyleSheet("color:#c0392b;")
        self.btn_cancel_dl.clicked.connect(self._on_cancel_download); dl_btn_row.addWidget(self.btn_cancel_dl)
        dl_btn_row.addStretch()
        af.addRow("", dl_btn_row)
        
        # 进度条行
        self.dl_bar = QProgressBar(); self.dl_bar.setVisible(False); self.dl_bar.setMaximum(100)
        af.addRow("", self.dl_bar)
        
        # 速度/进度信息行
        self.dl_label = QLabel(""); self.dl_label.setStyleSheet("font-size:11px;color:#666;padding:2px 0")
        self.dl_label.setVisible(False)
        af.addRow("", self.dl_label)

        self.vocal_check = QCheckBox("启用 Demucs 人声分离 (每首多花 1-3 分钟，提升准确率)")
        af.addRow("", self.vocal_check)
        l.addWidget(ag)

        # ── GPU 加速 ──
        self.gpu_group = QGroupBox("GPU 加速 (仅本地)"); gf = QFormLayout(self.gpu_group)
        self.gpu_group.setVisible(False)
        
        gpu_scan_row = QHBoxLayout()
        self.btn_scan_gpu = QPushButton("扫描显卡"); self.btn_scan_gpu.setMaximumWidth(80)
        self.btn_scan_gpu.clicked.connect(self._on_scan_gpu)
        gpu_scan_row.addWidget(self.btn_scan_gpu)
        self.gpu_info_label = QLabel("点击扫描检测显卡"); self.gpu_info_label.setStyleSheet("font-size:11px;color:#666")
        gpu_scan_row.addWidget(self.gpu_info_label)
        gpu_scan_row.addStretch()
        gf.addRow("", gpu_scan_row)
        
        gpu_install_row = QHBoxLayout()
        self.btn_install_gpu = QPushButton("安装 GPU 加速 (PyTorch CUDA ~2.5GB)")
        self.btn_install_gpu.clicked.connect(self._on_install_gpu)
        self.btn_install_gpu.setEnabled(False)
        gpu_install_row.addWidget(self.btn_install_gpu)
        self.btn_cancel_gpu = QPushButton("取消"); self.btn_cancel_gpu.setVisible(False)
        self.btn_cancel_gpu.setStyleSheet("color:#c0392b;")
        self.btn_cancel_gpu.clicked.connect(self._on_cancel_gpu)
        gpu_install_row.addWidget(self.btn_cancel_gpu)
        gpu_install_row.addStretch()
        gf.addRow("", gpu_install_row)
        
        self.gpu_progress = QProgressBar(); self.gpu_progress.setVisible(False); self.gpu_progress.setMaximum(100)
        gf.addRow("", self.gpu_progress)
        self.gpu_progress_label = QLabel(""); self.gpu_progress_label.setStyleSheet("font-size:11px;color:#666")
        self.gpu_progress_label.setVisible(False)
        gf.addRow("", self.gpu_progress_label)
        
        self.gpu_check = QCheckBox("启用 GPU 加速")
        gf.addRow("", self.gpu_check)
        l.addWidget(self.gpu_group)

        lg = QGroupBox("歌词输出"); lf = QFormLayout(lg)
        dr = QHBoxLayout(); self.lrc_input = QLineEdit()
        self.lrc_input.setPlaceholderText("留空 = 与音频文件同目录"); dr.addWidget(self.lrc_input)
        bb = QPushButton("浏览"); bb.clicked.connect(lambda: self._browse(self.lrc_input)); dr.addWidget(bb)
        lf.addRow("LRC 目录:", dr); l.addWidget(lg)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save); btns.rejected.connect(self.reject); l.addWidget(btns)

    def _load_config(self):
        c = self.config
        i = 0 if c.asr.provider == "groq" else 1; self.provider_combo.setCurrentIndex(i)
        self.api_input.setText(c.groq_api_key)
        self.xunfei_input.setText(c.xunfei_api_key)
        li = [j for j in range(self.lang_combo.count()) if self.lang_combo.itemData(j) == c.asr.language]
        self.lang_combo.setCurrentIndex(li[0] if li else 0)
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == c.asr.local_model: self.model_combo.setCurrentIndex(i); break
        self.vocal_check.setChecked(c.asr.use_vocal_separation)
        self.gpu_check.setChecked(c.asr.use_gpu)
        if c.output_lrc_dir: self.lrc_input.setText(c.output_lrc_dir)
        # 自动扫描显卡
        self._on_scan_gpu()

    def _on_prov(self, idx):
        is_local = self.provider_combo.itemData(idx) == "local"
        self.api_input.setVisible(not is_local)
        self.model_combo.setVisible(is_local)
        self.btn_dl.setVisible(is_local)
        self.btn_cancel_dl.setVisible(False)
        self.dl_bar.setVisible(False)
        self.dl_label.setVisible(False)
        self.gpu_group.setVisible(is_local)

    def _on_download(self):
        model = self.model_combo.currentData()
        self.btn_dl.setVisible(False); self.btn_cancel_dl.setVisible(True)
        self.dl_bar.setVisible(True); self.dl_bar.setValue(0)
        self.dl_label.setVisible(True); self.dl_label.setText("")
        self.worker = _DownloadWorker(model)
        self.worker.progress.connect(self._on_dl_progress)
        self.worker.finished.connect(self._on_dl_done)
        self.worker.start()

    def _on_dl_progress(self, pct, msg):
        self.dl_bar.setValue(pct)
        self.dl_label.setText(msg)

    def _on_cancel_download(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.cancel()
            self.dl_label.setText("正在取消...")
            self.btn_cancel_dl.setEnabled(False)

    def _on_dl_done(self, ok, msg):
        self.btn_dl.setVisible(True); self.btn_cancel_dl.setVisible(False)
        self.btn_cancel_dl.setEnabled(True)
        self.dl_bar.setVisible(False); self.dl_label.setVisible(False)
        if ok: QMessageBox.information(self, "完成", msg)
        elif "取消" in msg:
            pass  # 用户主动取消，不弹错误框
        else: QMessageBox.critical(self, "下载失败", msg)

    def _on_scan_gpu(self):
        self.btn_scan_gpu.setEnabled(False)
        self.gpu_info_label.setText("扫描中...")
        self._gpu_detector = _GPUDetectWorker()
        self._gpu_detector.result_ready.connect(self._on_gpu_detected)
        self._gpu_detector.start()
    
    def _on_gpu_detected(self, info: str):
        self.btn_scan_gpu.setEnabled(True)
        self.gpu_info_label.setText(info)
        has_gpu = info.startswith("✅")
        cuda_ready = "CUDA 已就绪" in info
        if cuda_ready:
            self.btn_install_gpu.setText("CUDA 已安装 ✓")
            self.btn_install_gpu.setEnabled(False)
        else:
            self.btn_install_gpu.setEnabled(has_gpu)
            self.btn_install_gpu.setText("安装 GPU 加速 (PyTorch CUDA ~2.5GB)")
    
    def _on_install_gpu(self):
        self.btn_install_gpu.setVisible(False)
        self.btn_cancel_gpu.setVisible(True)
        self.gpu_progress.setVisible(True); self.gpu_progress.setValue(0)
        self.gpu_progress_label.setVisible(True); self.gpu_progress_label.setText("")
        self._gpu_installer = _GPUInstallWorker()
        self._gpu_installer.progress.connect(self._on_gpu_dl_progress)
        self._gpu_installer.finished.connect(self._on_gpu_installed)
        self._gpu_installer.start()
    
    def _on_cancel_gpu(self):
        if hasattr(self, '_gpu_installer') and self._gpu_installer.isRunning():
            self._gpu_installer.cancel()
            self.gpu_progress_label.setText("正在取消...")
            self.btn_cancel_gpu.setEnabled(False)
    
    def _on_gpu_dl_progress(self, pct: int, msg: str):
        if pct >= 0:
            self.gpu_progress.setValue(pct)
        self.gpu_progress_label.setText(msg)
    
    def _on_gpu_installed(self, ok: bool, msg: str):
        self.btn_install_gpu.setVisible(True)
        self.btn_cancel_gpu.setVisible(False)
        self.btn_cancel_gpu.setEnabled(True)
        self.gpu_progress.setVisible(False)
        self.gpu_progress_label.setVisible(False)
        if "取消" in msg:
            self.btn_install_gpu.setEnabled(True)
            return  # 用户主动取消，不弹框
        if ok:
            self.gpu_check.setChecked(True)
            # 直接保存配置（不用 _save() 因为它内部会 accept 导致 done(42) 无效）
            c = self.config
            c.asr.use_gpu = True
            config_manager.config = c
            config_manager.save()
            QMessageBox.information(self, "安装完成", msg + "\n\n点击确定后将重启应用。")
            self.done(42)  # 特殊返回码：请求重启
        else:
            self.btn_install_gpu.setEnabled(True)
            QMessageBox.critical(self, "安装失败", msg)

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d: edit.setText(d)

    def _save(self):
        c = self.config
        c.asr.provider = self.provider_combo.currentData()
        c.asr.language = self.lang_combo.currentData()
        c.asr.local_model = self.model_combo.currentData()
        c.asr.use_vocal_separation = self.vocal_check.isChecked()
        c.asr.use_gpu = self.gpu_check.isChecked()
        key = self.api_input.text().strip(); c.groq_api_key = key
        if key: os.environ["GROQ_API_KEY"] = key
        xunfei_key = self.xunfei_input.text().strip(); c.xunfei_api_key = xunfei_key
        if xunfei_key: os.environ["XUNFEI_API_KEY"] = xunfei_key
        d = self.lrc_input.text().strip(); c.output_lrc_dir = d if d else None
        config_manager.config = c; config_manager.save()
        self.accept()
