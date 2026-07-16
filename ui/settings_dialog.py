"""设置对话框"""
import subprocess
import sys

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import AppConfig, config_manager
from core.process_utils import hidden_window_kwargs
from core.runtime_detection import detect_hardware, select_runtime
from core.runtime_manager import RuntimeInstallCancelled, RuntimeManagerError
from core.runtime_setup import RuntimeSetupResult, RuntimeSetupService
from core.voice_cache import (
    app_cache_dir,
    cache_stats,
    clear_app_cache,
    sent_transfer_cache_dir,
    voice_cache_dir,
)
from ui.theme import polish_widget_tree


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


class _TranslationInstallWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, source_language: str, target_language: str):
        super().__init__()
        self.source_language = source_language
        self.target_language = target_language

    def run(self):
        try:
            from core.lyrics_translation import install_local_translation_package

            message = install_local_translation_package(
                self.source_language, self.target_language
            )
            self.finished.emit(True, message)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class SettingsDialog(QDialog):
    restart_requested = pyqtSignal()  # GPU 安装完成后请求重启
    OPEN_MODEL_LIBRARY = 43

    def __init__(self, config: AppConfig, parent=None, section: str = "recognition"):
        super().__init__(parent); self.config = config
        self.section = section
        self._setup_ui(); self._load_config(); self._refresh_cache_stats()
        polish_widget_tree(self)
        self.setFixedSize(720, self._preferred_height)

    def _setup_ui(self):
        section_index = {
            "recognition": 0,
            "lyrics": 1,
            "shortcuts": 2,
            "cache": 3,
            "local_ai": 4,
        }.get(self.section, 0)
        section_title = ("语音识别", "歌词输出", "快捷键", "缓存", "本地部署 AI")[section_index]
        self.setWindowTitle(f"偏好设置 - {section_title}")
        self.setMinimumWidth(620)
        section_heights = {
            "recognition": 600,
            "lyrics": 570,
            "shortcuts": 350,
            "cache": 430,
            "local_ai": 500,
        }
        self._preferred_height = section_heights.get(self.section, 520)
        self.resize(720, self._preferred_height)
        l = QVBoxLayout(self)

        # 设置分类由顶栏“设置”菜单选择；对话框仅展示被选中的单个分类。
        self.settings_stack = _CurrentPageStack()
        recognition_page, recognition_layout = self._create_settings_section("语音识别")
        lyrics_page, lyrics_layout = self._create_settings_section("歌词输出")
        shortcut_page, shortcut_layout = self._create_settings_section("快捷键")
        cache_page, cache_layout = self._create_settings_section("缓存")
        local_ai_page, local_ai_layout = self._create_settings_section("本地部署 AI")
        for page in (recognition_page, lyrics_page, shortcut_page, cache_page, local_ai_page):
            self.settings_stack.addWidget(page)
        l.addWidget(self.settings_stack)
        self.settings_stack.setCurrentIndex(section_index)

        ag = QGroupBox("语音识别 (ASR)"); af = QFormLayout(ag)
        self.asr_form = af
        self.active_asr_label = QLabel("")
        self.active_asr_label.setStyleSheet("font-weight:600;color:#245B9E")
        af.addRow("当前识别模型:", self.active_asr_label)
        self.open_model_library_button = QPushButton("打开模型库选择模型")
        self.open_model_library_button.clicked.connect(
            lambda: self.done(self.OPEN_MODEL_LIBRARY)
        )
        af.addRow("", self.open_model_library_button)

        self.lang_combo = QComboBox()
        for t, v in [("自动检测", None), ("中文", "zh"), ("英语", "en"), ("日语", "ja"), ("韩语", "ko")]:
            self.lang_combo.addItem(t, v)
        af.addRow("默认语言:", self.lang_combo)

        self.vocal_check = QCheckBox("启用 Demucs 人声分离 (每首多花 1-3 分钟，提升准确率)")
        af.addRow("", self.vocal_check)
        recognition_layout.addWidget(ag)

        # ── GPU 加速 ──
        self.gpu_group = QGroupBox("本地识别运行时"); gf = QFormLayout(self.gpu_group)
        self.gpu_group.setVisible(True)

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

        translation_group = QGroupBox("歌词翻译")
        translation_form = QFormLayout(translation_group)
        self.translation_engine_combo = QComboBox()
        self.translation_engine_combo.addItem("AI 接口（在线或本地模型）", "ai")
        self.translation_engine_combo.addItem("本地离线翻译库（Argos）", "local")
        translation_form.addRow("默认引擎:", self.translation_engine_combo)
        language_items = [("中文", "zh"), ("英语", "en"), ("日语", "ja"), ("韩语", "ko")]
        self.translation_source_combo = QComboBox()
        self.translation_target_combo = QComboBox()
        self.translation_source_combo.addItem("自动检测", "auto")
        for label, code in language_items:
            self.translation_source_combo.addItem(label, code)
            self.translation_target_combo.addItem(label, code)
        self.translation_source_combo.currentIndexChanged.connect(
            self._refresh_translation_package_status
        )
        self.translation_target_combo.currentIndexChanged.connect(
            self._refresh_translation_package_status
        )
        translation_form.addRow("源语言:", self.translation_source_combo)
        translation_form.addRow("目标语言:", self.translation_target_combo)
        self.translation_package_status = QLabel("")
        self.translation_package_status.setWordWrap(True)
        self.translation_package_status.setStyleSheet("font-size:11px;color:#666")
        translation_form.addRow("本地库:", self.translation_package_status)
        self.translation_download_button = QPushButton("下载所选本地翻译库")
        self.translation_download_button.clicked.connect(self._on_download_translation_package)
        translation_form.addRow("", self.translation_download_button)
        translation_hint = QLabel(
            "本地库下载后可完全离线翻译；AI 翻译使用“本地部署 AI”页选中的接口。"
        )
        translation_hint.setWordWrap(True)
        translation_hint.setStyleSheet("font-size:11px;color:#666")
        translation_form.addRow("", translation_hint)
        lyrics_layout.addWidget(translation_group)
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
        self.voice_cache_stats = QLabel("")
        self.voice_cache_stats.setStyleSheet("font-size:11px;color:#666")
        cache_form.addRow("语音缓存统计:", self.voice_cache_stats)
        self.sent_cache_path = QLabel(str(sent_transfer_cache_dir()))
        self.sent_cache_path.setWordWrap(True)
        self.sent_cache_path.setStyleSheet("font-size:11px;color:#666")
        cache_form.addRow("已发送文件缓存:", self.sent_cache_path)
        self.sent_cache_stats = QLabel("")
        self.sent_cache_stats.setStyleSheet("font-size:11px;color:#666")
        cache_form.addRow("文件缓存统计:", self.sent_cache_stats)
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

        local_ai_group = QGroupBox("OpenAI 兼容接口")
        local_ai_form = QFormLayout(local_ai_group)
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItem("在线 AI（密钥管理中的 DeepSeek）", "online")
        self.ai_provider_combo.addItem("本地部署 AI", "local")
        local_ai_form.addRow("AI 来源:", self.ai_provider_combo)

        self.local_ai_preset = QComboBox()
        self.local_ai_preset.addItem("自定义", "custom")
        self.local_ai_preset.addItem("Ollama", "http://127.0.0.1:11434/v1")
        self.local_ai_preset.addItem("LM Studio", "http://127.0.0.1:1234/v1")
        self.local_ai_preset.currentIndexChanged.connect(self._apply_local_ai_preset)
        local_ai_form.addRow("快速预设:", self.local_ai_preset)

        self.local_ai_base_url_input = QLineEdit()
        self.local_ai_base_url_input.setPlaceholderText("http://127.0.0.1:11434/v1")
        local_ai_form.addRow("接口地址:", self.local_ai_base_url_input)
        self.local_ai_model_input = QLineEdit()
        self.local_ai_model_input.setPlaceholderText("例如 qwen3:8b 或当前已加载模型名")
        local_ai_form.addRow("模型名称:", self.local_ai_model_input)
        self.local_ai_key_input = QLineEdit()
        self.local_ai_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.local_ai_key_input.setPlaceholderText("可选；本地服务要求鉴权时再填写")
        local_ai_form.addRow("API Key:", self.local_ai_key_input)
        local_ai_hint = QLabel(
            "软件调用标准的 /v1/chat/completions 接口。Ollama、LM Studio 和其他 OpenAI "
            "兼容服务均可接入；本地接口默认不要求 API Key。"
        )
        local_ai_hint.setWordWrap(True)
        local_ai_hint.setStyleSheet("font-size:11px;color:#666")
        local_ai_form.addRow("", local_ai_hint)
        local_ai_layout.addWidget(local_ai_group)
        local_ai_layout.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
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
        self.active_asr_label.setText(self._active_asr_name())
        li = [j for j in range(self.lang_combo.count()) if self.lang_combo.itemData(j) == c.asr.language]
        self.lang_combo.setCurrentIndex(li[0] if li else 0)
        self.vocal_check.setChecked(c.asr.use_vocal_separation)
        self.gpu_check.setChecked(c.asr.use_gpu)
        if c.output_lrc_dir: self.lrc_input.setText(c.output_lrc_dir)
        self.voice_shortcut_edit.setKeySequence(QKeySequence(c.voice_input_shortcut))
        ai_provider_index = self.ai_provider_combo.findData(c.ai_provider)
        self.ai_provider_combo.setCurrentIndex(max(0, ai_provider_index))
        self.local_ai_base_url_input.setText(c.local_ai_base_url)
        self.local_ai_model_input.setText(c.local_ai_model_name)
        self.local_ai_key_input.setText(c.local_ai_api_key)
        translation_engine_index = self.translation_engine_combo.findData(c.translation_engine)
        self.translation_engine_combo.setCurrentIndex(max(0, translation_engine_index))
        source_index = self.translation_source_combo.findData(c.translation_source_language)
        target_index = self.translation_target_combo.findData(c.translation_target_language)
        self.translation_source_combo.setCurrentIndex(max(0, source_index))
        self.translation_target_combo.setCurrentIndex(max(0, target_index))
        if self.section == "lyrics":
            self._refresh_translation_package_status()
        # 仅打开语音识别分类时扫描显卡，避免其他设置页启动无关后台任务。
        if self.section == "recognition":
            self._on_scan_gpu()

    def _active_asr_name(self) -> str:
        provider = self.config.asr.provider
        if provider == "groq":
            return "在线模型 · Groq Whisper Large V3"
        if provider == "xunfei":
            return "在线模型 · 讯飞云端识别"
        return f"本地模型 · Whisper {self.config.asr.local_model}"

    def _apply_local_ai_preset(self, index: int):
        endpoint = self.local_ai_preset.itemData(index)
        if endpoint and endpoint != "custom":
            self.local_ai_base_url_input.setText(endpoint)

    def _refresh_translation_package_status(self, _index: int = -1):
        source = self.translation_source_combo.currentData()
        target = self.translation_target_combo.currentData()
        if source == "auto":
            self.translation_package_status.setText(
                "批量翻译会逐份自动检测；下载本地库时请先选择具体源语言"
            )
            self.translation_download_button.setEnabled(False)
            return
        if source == target:
            self.translation_package_status.setText("源语言和目标语言不能相同")
            self.translation_download_button.setEnabled(False)
            return
        from core.lyrics_translation import local_translation_available

        installed = local_translation_available(source, target)
        self.translation_package_status.setText(
            f"{source} → {target}：{'已安装 ✓' if installed else '未安装'}"
        )
        self.translation_download_button.setEnabled(not installed)

    def _on_download_translation_package(self):
        source = self.translation_source_combo.currentData()
        target = self.translation_target_combo.currentData()
        if source == "auto" or source == target:
            return
        self.translation_download_button.setEnabled(False)
        self.translation_package_status.setText(f"正在下载并安装 {source} → {target}…")
        self._translation_installer = _TranslationInstallWorker(source, target)
        self._translation_installer.finished.connect(self._on_translation_package_installed)
        self._translation_installer.start()

    def _on_translation_package_installed(self, success: bool, message: str):
        if success:
            self._refresh_translation_package_status()
            return
        self.translation_package_status.setText(message)
        self.translation_download_button.setEnabled(True)
        QMessageBox.warning(self, "本地翻译库", message)

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
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_cache_dir())))

    def _refresh_cache_stats(self):
        stats = cache_stats()
        self.voice_cache_stats.setText(
            f"{stats['voice_count']} 个文件，{_format_cache_size(stats['voice_size'])}"
        )
        self.sent_cache_stats.setText(
            f"{stats['sent_count']} 个文件，{_format_cache_size(stats['sent_size'])}"
        )
        self.cache_status.setText(
            f"缓存合计：{stats['total_count']} 个文件，"
            f"{_format_cache_size(stats['total_size'])}"
        )

    def _clear_voice_cache(self):
        reply = QMessageBox.question(
            self,
            "清理缓存",
            "将删除语音录音和已成功回传的文件缓存；"
            "不会删除待回传文件、模型、素材或正式处理结果。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_app_cache()
        except OSError as exc:
            QMessageBox.warning(self, "清理缓存", f"无法清理缓存：{exc}")
            return
        self._refresh_cache_stats()
        self.cache_status.setText(
            f"已清理 {removed['total_count']} 个缓存文件，"
            f"释放 {_format_cache_size(removed['total_size'])}。"
        )

    def _save(self):
        c = self.config
        c.asr.language = self.lang_combo.currentData()
        c.asr.use_vocal_separation = self.vocal_check.isChecked()
        c.asr.use_gpu = self.gpu_check.isChecked()
        d = self.lrc_input.text().strip(); c.output_lrc_dir = d if d else None
        shortcut = self.voice_shortcut_edit.keySequence().toString().strip()
        c.voice_input_shortcut = shortcut or "Ctrl+Shift+Space"
        c.ai_provider = self.ai_provider_combo.currentData()
        c.local_ai_base_url = self.local_ai_base_url_input.text().strip().rstrip("/")
        c.local_ai_model_name = self.local_ai_model_input.text().strip()
        c.local_ai_api_key = self.local_ai_key_input.text().strip()
        c.translation_engine = self.translation_engine_combo.currentData()
        c.translation_source_language = self.translation_source_combo.currentData()
        c.translation_target_language = self.translation_target_combo.currentData()
        config_manager.config = c; config_manager.save()
        self.accept()


def _format_cache_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"
