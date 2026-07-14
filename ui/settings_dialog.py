"""设置对话框"""
import os, subprocess, sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QCheckBox, QPushButton,
    QGroupBox, QLabel, QDialogButtonBox, QFileDialog, QKeySequenceEdit, QProgressBar, QMessageBox,
    QWidget, QStackedWidget,
)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QThread
from PyQt6.QtGui import QDesktopServices, QKeySequence
from core.config import AppConfig, config_manager
from core.model_download import DownloadCancelled, ModelDownloadError, download_model
from core.runtime_detection import detect_hardware, select_runtime
from core.runtime_manager import RuntimeInstallCancelled, RuntimeManagerError
from core.runtime_setup import RuntimeSetupResult, RuntimeSetupService
from core.process_utils import hidden_window_kwargs
from core.voice_cache import clear_voice_cache, voice_cache_dir


class _CurrentPageStack(QStackedWidget):
    """只按当前页计算尺寸，避免隐藏页撑出大块空白。"""

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current else super().minimumSizeHint()


class _GPUDetectWorker(QThread):
    """后台扫描显卡"""
    result_ready = pyqtSignal(str)  # GPU 名称 或 错误信息
    
    def run(self):
        try:
            # 先试 nvidia-smi
            import subprocess as sp
            r = sp.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                       capture_output=True, text=True, timeout=10,
                       **hidden_window_kwargs())
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
                **hidden_window_kwargs(),
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


class _RuntimeDetectWorker(QThread):
    """Detect all supported GPU vendors without importing the bundled Torch."""

    result_ready = pyqtSignal(object)

    def run(self):
        try:
            report = detect_hardware()
            self.result_ready.emit((report, select_runtime(report), None))
        except Exception as exc:
            self.result_ready.emit((None, None, str(exc)))


class _RuntimeSetupWorker(QThread):
    """Install and validate the selected external runtime without blocking the UI."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object)

    def __init__(self):
        super().__init__()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        try:
            result = RuntimeSetupService().configure(
                progress=lambda percent, message: self.progress.emit(percent, message),
                cancelled=lambda: self._cancelled or self.isInterruptionRequested(),
            )
            self.finished.emit(True, result)
        except RuntimeInstallCancelled:
            self.finished.emit(False, "运行时配置已取消")
        except RuntimeManagerError as exc:
            self.finished.emit(False, str(exc))
        except Exception as exc:
            self.finished.emit(False, f"运行时配置失败：{exc}")


class _DownloadWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, model: str):
        super().__init__(); self.model = model; self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        try:
            result = download_model(
                self.model,
                progress=lambda percent, message: self.progress.emit(percent, message),
                cancelled=lambda: self._cancelled or self.isInterruptionRequested(),
            )
            message = (
                f"{self.model} 模型已缓存并通过校验"
                if result.cached
                else f"{self.model} 模型已从 GitHub Release 下载完成"
            )
            self.finished.emit(True, message)
        except DownloadCancelled:
            self.finished.emit(False, "下载已取消")
        except ModelDownloadError as exc:
            self.finished.emit(False, str(exc))
        except Exception as exc:
            self.finished.emit(False, f"下载失败: {exc}")


class SettingsDialog(QDialog):
    restart_requested = pyqtSignal()  # GPU 安装完成后请求重启
    
    def __init__(self, config: AppConfig, parent=None, section: str = "recognition"):
        super().__init__(parent); self.config = config
        self.section = section
        self._setup_ui(); self._load_config()

    def _setup_ui(self):
        section_index = {
            "recognition": 0,
            "lyrics": 1,
            "shortcuts": 2,
            "cache": 3,
        }.get(self.section, 0)
        section_title = ("语音识别", "歌词输出", "快捷键", "缓存")[section_index]
        self.setWindowTitle(f"偏好设置 - {section_title}"); self.setMinimumWidth(500)
        l = QVBoxLayout(self)

        # 设置分类由顶栏“设置”菜单选择；对话框仅展示被选中的单个分类。
        self.settings_stack = _CurrentPageStack()
        recognition_page, recognition_layout = self._create_settings_section("语音识别")
        lyrics_page, lyrics_layout = self._create_settings_section("歌词输出")
        shortcut_page, shortcut_layout = self._create_settings_section("快捷键")
        cache_page, cache_layout = self._create_settings_section("缓存")
        for page in (recognition_page, lyrics_page, shortcut_page, cache_page):
            self.settings_stack.addWidget(page)
        l.addWidget(self.settings_stack)
        self.settings_stack.setCurrentIndex(section_index)

        ag = QGroupBox("语音识别 (ASR)"); af = QFormLayout(ag)
        self.asr_form = af
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("云端", "cloud")
        self.provider_combo.addItem("本地", "local")
        self.provider_combo.currentIndexChanged.connect(self._on_prov)
        af.addRow("识别引擎:", self.provider_combo)

        self.cloud_provider_label = QLabel("云端服务:")
        self.cloud_provider_combo = QComboBox()
        self.cloud_provider_combo.addItem("Groq", "groq")
        self.cloud_provider_combo.addItem("讯飞", "xunfei")
        self.cloud_provider_combo.currentIndexChanged.connect(
            lambda _index: self._on_prov(self.provider_combo.currentIndex())
        )
        af.addRow(self.cloud_provider_label, self.cloud_provider_combo)

        self.api_input = QLineEdit(); self.api_input.setPlaceholderText("输入 API Key...")
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.groq_input_label = QLabel("Groq Key:")
        af.addRow(self.groq_input_label, self.api_input)
        self.groq_key_status = QLabel("已在密钥管理中配置 ✓")
        self.groq_key_status.setStyleSheet("color:#248A4A;font-weight:600")
        self.groq_status_label = QLabel("Groq Key:")
        af.addRow(self.groq_status_label, self.groq_key_status)
        self.groq_key_link = QLabel(
            '<a href="https://console.groq.com/keys" style="color:#1976D2">免费获取 Groq Key</a>'
        )
        self.groq_key_link.setOpenExternalLinks(True)
        self.groq_key_link.setStyleSheet("font-size:11px")
        af.addRow("", self.groq_key_link)
        self.groq_key_notice = QLabel("Key 将以明文保存在当前用户的本机配置中")
        self.groq_key_notice.setStyleSheet("font-size:10px;color:#888")
        af.addRow("", self.groq_key_notice)

        self.xunfei_key_label = QLabel("讯飞 Key:")
        self.xunfei_key_status = QLabel("已在密钥管理中配置 ✓")
        self.xunfei_key_status.setStyleSheet("color:#248A4A;font-weight:600")
        af.addRow(self.xunfei_key_label, self.xunfei_key_status)
        self.xunfei_notice = QLabel("讯飞识别尚待接入；当前可保存并切换服务配置。")
        self.xunfei_notice.setStyleSheet("font-size:10px;color:#888")
        self.xunfei_notice.setWordWrap(True)
        af.addRow("", self.xunfei_notice)

        # 保留字段以兼容已有配置，讯飞 Provider 实现前不在界面中展示。
        self.xunfei_input = QLineEdit()
        self.xunfei_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.lang_combo = QComboBox()
        for t, v in [("自动检测", None), ("中文", "zh"), ("英语", "en"), ("日语", "ja"), ("韩语", "ko")]:
            self.lang_combo.addItem(t, v)
        af.addRow("默认语言:", self.lang_combo)

        self.model_combo = QComboBox()
        for t, v in [
            ("tiny (~144 MB, 最快)", "tiny"),
            ("base (~139 MB, 推荐)", "base"),
            ("small (~922 MB)", "small"),
            ("medium (~2.85 GB, 更准确)", "medium"),
        ]:
            self.model_combo.addItem(t, v)
        self.model_combo.setVisible(False)
        self.local_model_label = QLabel("本地模型:")
        af.addRow(self.local_model_label, self.model_combo)

        # 下载按钮行
        dl_btn_row = QHBoxLayout()
        self.btn_dl = QPushButton("下载模型"); self.btn_dl.setVisible(False)
        self.btn_dl.clicked.connect(self._on_download); dl_btn_row.addWidget(self.btn_dl)
        self.btn_cancel_dl = QPushButton("取消下载"); self.btn_cancel_dl.setVisible(False)
        self.btn_cancel_dl.setStyleSheet("color:#c0392b;")
        self.btn_cancel_dl.clicked.connect(self._on_cancel_download); dl_btn_row.addWidget(self.btn_cancel_dl)
        dl_btn_row.addStretch()
        self.download_buttons_row = af.rowCount()
        af.addRow("", dl_btn_row)
        
        # 进度条行
        self.dl_bar = QProgressBar(); self.dl_bar.setVisible(False); self.dl_bar.setMaximum(100)
        self.download_progress_row = af.rowCount()
        af.addRow("", self.dl_bar)
        
        # 速度/进度信息行
        self.dl_label = QLabel(""); self.dl_label.setStyleSheet("font-size:11px;color:#666;padding:2px 0")
        self.dl_label.setVisible(False)
        self.download_message_row = af.rowCount()
        af.addRow("", self.dl_label)

        self.vocal_check = QCheckBox("启用 Demucs 人声分离 (每首多花 1-3 分钟，提升准确率)")
        af.addRow("", self.vocal_check)
        recognition_layout.addWidget(ag)

        # ── GPU 加速 ──
        self.gpu_group = QGroupBox("本地识别运行时"); gf = QFormLayout(self.gpu_group)
        self.gpu_group.setVisible(False)
        
        gpu_scan_row = QHBoxLayout()
        self.btn_scan_gpu = QPushButton("重新检测"); self.btn_scan_gpu.setMaximumWidth(80)
        self.btn_scan_gpu.clicked.connect(self._on_scan_gpu)
        gpu_scan_row.addWidget(self.btn_scan_gpu)
        self.gpu_info_label = QLabel("检测当前电脑的推荐运行时"); self.gpu_info_label.setStyleSheet("font-size:11px;color:#666")
        gpu_scan_row.addWidget(self.gpu_info_label)
        gpu_scan_row.addStretch()
        gf.addRow("", gpu_scan_row)
        
        gpu_install_row = QHBoxLayout()
        self.btn_install_gpu = QPushButton("自动配置本地识别")
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
        
        self.gpu_check = QCheckBox("当前 GPU 运行时已启用")
        self.gpu_check.setEnabled(False)
        gf.addRow("", self.gpu_check)
        recognition_layout.addWidget(self.gpu_group)

        lg = QGroupBox("歌词输出"); lf = QFormLayout(lg)
        dr = QHBoxLayout(); self.lrc_input = QLineEdit()
        self.lrc_input.setPlaceholderText("留空 = 与音频文件同目录"); dr.addWidget(self.lrc_input)
        bb = QPushButton("浏览"); bb.clicked.connect(lambda: self._browse(self.lrc_input)); dr.addWidget(bb)
        lf.addRow("LRC 目录:", dr); lyrics_layout.addWidget(lg)
        lyrics_layout.addStretch()

        shortcut_group = QGroupBox("快捷键")
        shortcut_form = QFormLayout(shortcut_group)
        self.voice_shortcut_edit = QKeySequenceEdit()
        self.voice_shortcut_edit.setToolTip("在 AI 模式中开始或停止语音输入")
        shortcut_form.addRow("语音输入:", self.voice_shortcut_edit)
        shortcut_hint = QLabel("默认 Ctrl+Shift+Space；AI 模式未启动时快捷键不会录音。")
        shortcut_hint.setWordWrap(True)
        shortcut_hint.setStyleSheet("font-size:11px;color:#666")
        shortcut_form.addRow("", shortcut_hint)
        shortcut_layout.addWidget(shortcut_group)
        shortcut_layout.addStretch()

        cache_group = QGroupBox("缓存")
        cache_form = QFormLayout(cache_group)
        self.voice_cache_path = QLabel(str(voice_cache_dir()))
        self.voice_cache_path.setWordWrap(True)
        self.voice_cache_path.setStyleSheet("font-size:11px;color:#666")
        cache_form.addRow("语音录音缓存:", self.voice_cache_path)
        cache_actions = QHBoxLayout()
        open_cache_button = QPushButton("打开缓存文件夹")
        open_cache_button.clicked.connect(self._open_voice_cache)
        cache_actions.addWidget(open_cache_button)
        clear_cache_button = QPushButton("清理缓存")
        clear_cache_button.clicked.connect(self._clear_voice_cache)
        cache_actions.addWidget(clear_cache_button)
        cache_actions.addStretch()
        cache_form.addRow("", cache_actions)
        self.cache_status = QLabel("")
        self.cache_status.setStyleSheet("font-size:11px;color:#666")
        cache_form.addRow("", self.cache_status)
        cache_layout.addWidget(cache_group)
        cache_layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save); btns.rejected.connect(self.reject); l.addWidget(btns)

    def _create_settings_section(self, title_text: str) -> tuple[QWidget, QVBoxLayout]:
        """创建只显示单一设置分类的页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title_text)
        heading.setStyleSheet("font-size:18px;font-weight:700;color:#202124;padding:4px 0 8px 2px;")
        layout.addWidget(heading)
        return page, layout

    def _load_config(self):
        c = self.config
        i = 1 if c.asr.provider == "local" else 0; self.provider_combo.setCurrentIndex(i)
        cloud_index = self.cloud_provider_combo.findData(c.asr.provider)
        self.cloud_provider_combo.setCurrentIndex(cloud_index if cloud_index >= 0 else 0)
        self.api_input.clear()
        self.xunfei_input.setText(c.xunfei_api_key)
        li = [j for j in range(self.lang_combo.count()) if self.lang_combo.itemData(j) == c.asr.language]
        self.lang_combo.setCurrentIndex(li[0] if li else 0)
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == c.asr.local_model: self.model_combo.setCurrentIndex(i); break
        self.vocal_check.setChecked(c.asr.use_vocal_separation)
        self.gpu_check.setChecked(c.asr.use_gpu)
        if c.output_lrc_dir: self.lrc_input.setText(c.output_lrc_dir)
        self.voice_shortcut_edit.setKeySequence(QKeySequence(c.voice_input_shortcut))
        # 自动扫描显卡
        self._on_scan_gpu()
        self._refresh_cloud_provider_state()

    def _on_prov(self, idx):
        is_local = self.provider_combo.itemData(idx) == "local"
        is_groq = self.cloud_provider_combo.currentData() == "groq"
        is_xunfei = not is_local and not is_groq
        self.cloud_provider_label.setVisible(not is_local)
        self.cloud_provider_combo.setVisible(not is_local)
        show_groq_input = not is_local and is_groq and not bool(self.config.groq_api_key)
        show_groq_status = not is_local and is_groq and bool(self.config.groq_api_key)
        self._set_asr_row_visible(self.api_input, show_groq_input)
        self._set_asr_row_visible(self.groq_key_status, show_groq_status)
        self._set_asr_row_visible(self.groq_key_link, show_groq_input)
        self._set_asr_row_visible(self.groq_key_notice, show_groq_input)
        self._set_asr_row_visible(self.xunfei_key_status, is_xunfei)
        self._set_asr_row_visible(self.xunfei_notice, is_xunfei)
        self._set_asr_row_visible(self.model_combo, is_local)
        self.btn_dl.setVisible(is_local)
        self.btn_cancel_dl.setVisible(False)
        self.dl_bar.setVisible(False)
        self.dl_label.setVisible(False)
        self.asr_form.setRowVisible(self.download_buttons_row, is_local)
        self.asr_form.setRowVisible(self.download_progress_row, False)
        self.asr_form.setRowVisible(self.download_message_row, False)
        self.gpu_group.setVisible(is_local)
        self.settings_stack.updateGeometry()
        if self.isVisible():
            self.adjustSize()

    def _set_asr_row_visible(self, field: QWidget, visible: bool):
        """隐藏字段时连同 QFormLayout 的标签一起隐藏，避免残留空行。"""
        label = self.asr_form.labelForField(field)
        if label:
            label.setVisible(visible)
        field.setVisible(visible)

    def _refresh_cloud_provider_state(self):
        self.cloud_provider_combo.setItemText(
            0, "Groq ✓" if self.config.groq_api_key else "Groq"
        )
        self.cloud_provider_combo.setItemText(
            1, "讯飞 ✓" if self.config.xunfei_api_key else "讯飞"
        )
        self._on_prov(self.provider_combo.currentIndex())

    def _on_download(self):
        model = self.model_combo.currentData()
        self.btn_dl.setVisible(False); self.btn_cancel_dl.setVisible(True)
        self.dl_bar.setVisible(True); self.dl_bar.setValue(0)
        self.dl_label.setVisible(True); self.dl_label.setText("")
        self.asr_form.setRowVisible(self.download_buttons_row, True)
        self.asr_form.setRowVisible(self.download_progress_row, True)
        self.asr_form.setRowVisible(self.download_message_row, True)
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
        self.asr_form.setRowVisible(self.download_progress_row, False)
        self.asr_form.setRowVisible(self.download_message_row, False)
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
        if getattr(sys, "frozen", False):
            self.btn_install_gpu.setText("打包版内置 CPU 推理运行时")
            self.btn_install_gpu.setEnabled(False)
            return
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

    # The following handlers supersede the legacy bundled-Python pip installer above.
    # A packaged app now installs only signed external runtime bundles.
    def _on_scan_gpu(self):
        self.btn_scan_gpu.setEnabled(False)
        self.gpu_info_label.setText("正在检测硬件与驱动...")
        self._gpu_detector = _RuntimeDetectWorker()
        self._gpu_detector.result_ready.connect(self._on_gpu_detected)
        self._gpu_detector.start()

    def _on_gpu_detected(self, result):
        self.btn_scan_gpu.setEnabled(True)
        _report, selection, error = result
        if error:
            self.gpu_info_label.setText(f"检测失败：{error}")
            self.btn_install_gpu.setEnabled(False)
            return
        self._runtime_selection = selection
        if selection.variant.backend == "cpu":
            self.gpu_info_label.setText("未检测到可用 GPU，将配置 CPU 本地识别")
            self.btn_install_gpu.setText("配置 CPU 本地识别")
        else:
            adapter_name = selection.adapter.name if selection.adapter else "兼容 GPU"
            label = {
                "cuda": "CUDA GPU 推理",
                "winml": "Windows GPU 推理",
            }.get(selection.variant.backend, selection.variant.backend)
            self.gpu_info_label.setText(f"{adapter_name} · 推荐 {label}")
            self.btn_install_gpu.setText(f"自动配置 {label}")
        self.btn_install_gpu.setEnabled(True)

    def _on_install_gpu(self):
        self.btn_install_gpu.setVisible(False)
        self.btn_cancel_gpu.setVisible(True)
        self.gpu_progress.setVisible(True); self.gpu_progress.setValue(0)
        self.gpu_progress_label.setVisible(True); self.gpu_progress_label.setText("")
        self._gpu_installer = _RuntimeSetupWorker()
        self._gpu_installer.progress.connect(self._on_gpu_dl_progress)
        self._gpu_installer.finished.connect(self._on_gpu_installed)
        self._gpu_installer.start()

    def _on_cancel_gpu(self):
        if hasattr(self, "_gpu_installer") and self._gpu_installer.isRunning():
            self._gpu_installer.cancel()
            self.gpu_progress_label.setText("正在取消...")
            self.btn_cancel_gpu.setEnabled(False)

    def _on_gpu_installed(self, ok: bool, payload):
        self.btn_install_gpu.setVisible(True)
        self.btn_cancel_gpu.setVisible(False)
        self.btn_cancel_gpu.setEnabled(True)
        self.gpu_progress.setVisible(False)
        self.gpu_progress_label.setVisible(False)
        if not ok and "取消" in str(payload):
            self.btn_install_gpu.setEnabled(True)
            return
        if not ok:
            self.btn_install_gpu.setEnabled(True)
            QMessageBox.critical(self, "配置失败", str(payload))
            return

        result: RuntimeSetupResult = payload
        self.gpu_check.setChecked(result.uses_gpu)
        self.config.asr.use_gpu = result.uses_gpu
        config_manager.config = self.config
        config_manager.save()
        if result.install_result is None:
            QMessageBox.information(self, "配置完成", "已选择 CPU 本地识别。")
            return
        QMessageBox.information(
            self,
            "配置完成",
            "推理运行时已通过自检。点击确定后将重启应用以启用它。",
        )
        self.done(42)

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if d: edit.setText(d)

    def _open_voice_cache(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(voice_cache_dir())))

    def _clear_voice_cache(self):
        reply = QMessageBox.question(
            self,
            "清理语音缓存",
            "将删除本机语音输入录音缓存，不会删除模型、素材或歌词。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_voice_cache()
        except OSError as exc:
            QMessageBox.warning(self, "清理缓存", f"无法清理缓存：{exc}")
            return
        self.cache_status.setText(f"已清理 {removed} 个语音缓存文件。")

    def _save(self):
        c = self.config
        c.asr.provider = (
            "local"
            if self.provider_combo.currentData() == "local"
            else self.cloud_provider_combo.currentData()
        )
        c.asr.language = self.lang_combo.currentData()
        c.asr.local_model = self.model_combo.currentData()
        c.asr.use_vocal_separation = self.vocal_check.isChecked()
        c.asr.use_gpu = self.gpu_check.isChecked()
        key = self.api_input.text().strip()
        if key:
            c.groq_api_key = key
        if key: os.environ["GROQ_API_KEY"] = key
        xunfei_key = self.xunfei_input.text().strip(); c.xunfei_api_key = xunfei_key
        if xunfei_key: os.environ["XUNFEI_API_KEY"] = xunfei_key
        d = self.lrc_input.text().strip(); c.output_lrc_dir = d if d else None
        shortcut = self.voice_shortcut_edit.keySequence().toString().strip()
        c.voice_input_shortcut = shortcut or "Ctrl+Shift+Space"
        config_manager.config = c; config_manager.save()
        self.accept()
