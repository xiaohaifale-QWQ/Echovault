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

class _DownloadWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, model: str):
        super().__init__(); self.model = model

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
            
            if _os.path.exists(model_file) and _os.path.getsize(model_file) > 100000:
                self.finished.emit(True, f"{self.model} 模型已缓存")
                return

            _os.makedirs(cache, exist_ok=True)
            
            if self.model == "medium":
                # medium 分两片，需合并
                ok = self._download_medium(cache)
            else:
                url = f"{_GH_RELEASE}/{self.model}.pt"
                ok = self._download_file(url, model_file)
            
            if not ok:
                self.finished.emit(False, "下载失败, 请检查网络")
                return
            
            self.finished.emit(True, f"{self.model} 模型下载完成")

        except subprocess.CalledProcessError:
            self.finished.emit(False, "pip 安装失败")
        except Exception as e:
            self.finished.emit(False, str(e))

    def _load_model(self, model_file):
        """加载模型，绕过 SHA256 校验"""
        import whisper, torch, hashlib
        actual = hashlib.sha256(open(model_file, "rb").read()).hexdigest()
        whisper._MODELS[self.model] = whisper._MODELS.get(self.model,
            f"https://openaipublic.azureedge.net/main/whisper/models/{actual}/{self.model}.pt")
        whisper.load_model(self.model)

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
        import urllib.request, ssl, socket
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        socket.setdefaulttimeout(30)
        tmp = save_path + ".tmp"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Echovault/1.0"})
            for attempt in range(5):
                try:
                    resp = urllib.request.urlopen(req, context=ctx, timeout=60)
                    break
                except Exception as e:
                    if attempt == 4: raise
                    wait = 2 ** attempt
                    self.progress.emit(0, f"重试 {attempt+2}/5 (等待{wait}s)...")
                    import time; time.sleep(wait)
            total = int(resp.headers.get("Content-Length", 0))
            received = 0
            import time as _time; start = _time.time()
            with open(tmp, "wb") as f:
                while True:
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
                os.remove(tmp); return False
            os.replace(tmp, save_path); return True
        except Exception as e:
            if os.path.exists(tmp): os.remove(tmp)
            return False


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent); self.config = config
        self._setup_ui(); self._load_config()

    def _setup_ui(self):
        self.setWindowTitle("偏好设置"); self.setMinimumWidth(500)
        l = QVBoxLayout(self)

        ag = QGroupBox("语音识别 (ASR)"); af = QFormLayout(ag)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Groq Whisper (云端, 免费)", "groq")
        self.provider_combo.addItem("本地 Whisper (离线)", "local")
        self.provider_combo.currentIndexChanged.connect(self._on_prov)
        af.addRow("识别引擎:", self.provider_combo)

        self.api_input = QLineEdit(); self.api_input.setPlaceholderText("输入 API Key...")
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password); af.addRow("Groq Key:", self.api_input)
        kh = QLabel('<a href="https://console.groq.com/keys" style="color:#1976D2">免费获取 Groq Key</a>')
        kh.setOpenExternalLinks(True); kh.setStyleSheet("font-size:11px"); af.addRow("", kh)

        self.lang_combo = QComboBox()
        for t, v in [("自动检测", None), ("中文", "zh"), ("英语", "en"), ("日语", "ja"), ("韩语", "ko")]:
            self.lang_combo.addItem(t, v)
        af.addRow("默认语言:", self.lang_combo)

        self.model_combo = QComboBox()
        for t, v in [("tiny (39M, 最快)", "tiny"), ("base (74M, 推荐)", "base"), ("small (244M)", "small"), ("medium (769M, 更准)", "medium")]:
            self.model_combo.addItem(t, v)
        self.model_combo.setVisible(False); af.addRow("本地模型:", self.model_combo)

        # 下载按钮行
        dl_btn_row = QHBoxLayout()
        self.btn_dl = QPushButton("下载模型"); self.btn_dl.setVisible(False)
        self.btn_dl.clicked.connect(self._on_download); dl_btn_row.addWidget(self.btn_dl)
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
        li = [j for j in range(self.lang_combo.count()) if self.lang_combo.itemData(j) == c.asr.language]
        self.lang_combo.setCurrentIndex(li[0] if li else 0)
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == c.asr.local_model: self.model_combo.setCurrentIndex(i); break
        self.vocal_check.setChecked(c.asr.use_vocal_separation)
        if c.output_lrc_dir: self.lrc_input.setText(c.output_lrc_dir)

    def _on_prov(self, idx):
        is_local = self.provider_combo.itemData(idx) == "local"
        self.api_input.setVisible(not is_local)
        self.model_combo.setVisible(is_local)
        self.btn_dl.setVisible(is_local)
        self.dl_bar.setVisible(False)
        self.dl_label.setVisible(False)

    def _on_download(self):
        model = self.model_combo.currentData()
        self.btn_dl.setEnabled(False); self.dl_bar.setVisible(True); self.dl_bar.setValue(0)
        self.dl_label.setVisible(True); self.dl_label.setText("")
        self.worker = _DownloadWorker(model)
        self.worker.progress.connect(self._on_dl_progress)
        self.worker.finished.connect(self._on_dl_done)
        self.worker.start()

    def _on_dl_progress(self, pct, msg):
        self.dl_bar.setValue(pct)
        self.dl_label.setText(msg)

    def _on_dl_done(self, ok, msg):
        self.btn_dl.setEnabled(True); self.dl_bar.setVisible(False); self.dl_label.setVisible(False)
        if ok: QMessageBox.information(self, "完成", msg)
        else: QMessageBox.critical(self, "下载失败", msg)

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d: edit.setText(d)

    def _save(self):
        c = self.config
        c.asr.provider = self.provider_combo.currentData()
        c.asr.language = self.lang_combo.currentData()
        c.asr.local_model = self.model_combo.currentData()
        c.asr.use_vocal_separation = self.vocal_check.isChecked()
        key = self.api_input.text().strip(); c.groq_api_key = key
        if key: os.environ["GROQ_API_KEY"] = key
        d = self.lrc_input.text().strip(); c.output_lrc_dir = d if d else None
        config_manager.config = c; config_manager.save()
        self.accept()
