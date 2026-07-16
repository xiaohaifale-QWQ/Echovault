"""Top-level model library with separate recognition and separation cards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.audio_enhancement import (
    ENHANCEMENT_MODELS,
    download_enhancement_model,
    enhancement_model_installed,
)
from core.config import config_manager
from core.model_download import DownloadCancelled, download_model
from core.runtime_detection import detect_hardware, select_runtime
from core.separation_runtime import (
    active_separation_gpu_runtime,
    separation_gpu_available,
)
from core.vocal_separation import (
    SEPARATION_MODELS,
    SeparationCancelled,
    download_separation_model,
    separation_model_installed,
)
from ui.theme import polish_widget_tree


@dataclass(frozen=True)
class CatalogModel:
    category: str
    key: str
    name: str
    description: str
    speed: str
    quality: str
    size: str


@dataclass(frozen=True)
class OnlineModel:
    key: str
    name: str
    description: str
    speed: str


ONLINE_MODELS = (
    OnlineModel(
        "groq",
        "Groq Whisper Large V3",
        "高速云端歌词识别，适合网络稳定且已配置 Groq Key 的场景。",
        "很快",
    ),
    OnlineModel(
        "xunfei",
        "讯飞云端识别",
        "优先极速录音转写，未授权时自动回退流式语音听写。",
        "快",
    ),
)


WHISPER_MODELS = (
    CatalogModel("asr", "tiny", "Whisper Tiny", "快速预览与低配电脑", "最快", "基础", "约 144 MB"),
    CatalogModel(
        "asr", "base", "Whisper Base（推荐）", "日常歌词识别", "快", "中", "约 139 MB"
    ),
    CatalogModel(
        "asr", "small", "Whisper Small", "多语言歌词识别", "中等", "高", "约 922 MB"
    ),
    CatalogModel(
        "asr", "medium", "Whisper Medium", "高精度识别", "较慢", "更高", "约 2.85 GB"
    ),
)


class ModelInstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, category: str, model: str, parent=None):
        super().__init__(parent)
        self.category = category
        self.model = model

    def run(self):
        try:
            def callback(percent, message):
                self.progress.emit(percent, message)

            if self.category == "asr":
                download_model(
                    self.model,
                    progress=callback,
                    cancelled=self.isInterruptionRequested,
                )
            elif self.category == "separation":
                download_separation_model(
                    self.model,
                    progress=callback,
                    cancelled=self.isInterruptionRequested,
                )
            else:
                download_enhancement_model(
                    self.model,
                    progress=callback,
                    cancelled=self.isInterruptionRequested,
                )
            self.finished.emit(True, "安装完成")
        except (DownloadCancelled, SeparationCancelled):
            self.finished.emit(False, "安装已取消")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class ModelLibraryDialog(QDialog):
    """Central catalog for selecting online and local processing models."""

    model_state_changed = pyqtSignal()
    OPEN_ASR_SETTINGS = 42
    OPEN_KEY_MANAGER = 43

    def __init__(self, parent=None, *, config=None, initial_category: str = "all"):
        super().__init__(parent)
        self.config = config or config_manager.config
        self.initial_category = initial_category
        self._worker = None
        self._pending_local_model = ""
        self.setWindowTitle("模型库")
        self.resize(1050, 720)
        self._setup_ui()
        self.refresh_tables()
        self._refresh_runtime_status()
        polish_widget_tree(self)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("模型库")
        title.setStyleSheet("font-size:20px;font-weight:700")
        layout.addWidget(title)
        hint = QLabel(
            "在这里统一选择在线识别、本地 Whisper、音频分离与增强模型。"
            "在线服务的凭据仍由“密钥管理”保存。"
        )
        hint.setStyleSheet("color:#666")
        layout.addWidget(hint)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索模型名称、场景或描述")
        self.search_input.textChanged.connect(self.refresh_tables)
        layout.addWidget(self.search_input)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.cards_layout = QVBoxLayout(content)

        self.online_card, self.online_table = self._build_online_card()
        self.cards_layout.addWidget(self.online_card)

        self.asr_card, self.asr_table, self.asr_runtime_label = self._build_card(
            "本地 Whisper 模型",
            "下载后可离线把音乐或视频中的人声转换为带时间轴的文字；"
            "点击“使用”会同时切换到本地识别。",
            "asr",
        )
        asr_runtime_row = QHBoxLayout()
        asr_runtime_row.addWidget(QLabel("GPU 推理:"))
        asr_runtime_row.addWidget(self.asr_runtime_label, 1)
        self.asr_runtime_button = QPushButton("配置识别 GPU")
        self.asr_runtime_button.clicked.connect(
            lambda: self.done(self.OPEN_ASR_SETTINGS)
        )
        asr_runtime_row.addWidget(self.asr_runtime_button)
        self.asr_card.layout().insertLayout(2, asr_runtime_row)
        self.cards_layout.addWidget(self.asr_card)

        (
            self.separation_card,
            self.separation_table,
            self.separation_runtime_label,
        ) = self._build_card(
            "音频分离与增强模型",
            "Demucs 用于分离人声与伴奏；UVR 增强模型用于对分离后的人声降噪、"
            "去回声和混响。CPU/GPU 共用模型文件。",
            "separation",
        )
        separation_model_row = QHBoxLayout()
        separation_model_row.addWidget(QLabel("默认分离模型:"))
        self.separation_model_combo = QComboBox()
        for spec in SEPARATION_MODELS.values():
            self.separation_model_combo.addItem(spec.name, spec.key)
        model_index = self.separation_model_combo.findData(
            getattr(self.config.asr, "vocal_separation_model", "htdemucs")
        )
        self.separation_model_combo.setCurrentIndex(max(0, model_index))
        self.separation_model_combo.currentIndexChanged.connect(
            self._save_default_separation_model
        )
        separation_model_row.addWidget(self.separation_model_combo, 1)
        self.separation_card.layout().insertLayout(2, separation_model_row)
        separation_runtime_row = QHBoxLayout()
        separation_runtime_row.addWidget(QLabel("GPU 推理:"))
        self.separation_gpu_check = QCheckBox("优先使用 NVIDIA CUDA")
        self.separation_gpu_check.setChecked(
            bool(getattr(self.config.asr, "vocal_separation_use_gpu", False))
        )
        self.separation_gpu_check.toggled.connect(self._save_separation_gpu_preference)
        separation_runtime_row.addWidget(self.separation_gpu_check)
        separation_runtime_row.addWidget(self.separation_runtime_label, 1)
        self.separation_card.layout().insertLayout(3, separation_runtime_row)
        self.cards_layout.addWidget(self.separation_card)
        self.cards_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#555")
        footer.addWidget(self.status_label, 1)
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_install)
        footer.addWidget(self.cancel_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def _build_online_card(self):
        card = QGroupBox()
        card.setObjectName("onlineModelCard")
        card.setStyleSheet(
            "QGroupBox{background:white;border:1px solid #D8DEE7;border-radius:8px;"
            "margin-top:0;padding:10px}"
        )
        card_layout = QVBoxLayout(card)
        heading = QLabel("在线识别模型")
        heading.setStyleSheet("font-size:16px;font-weight:700")
        card_layout.addWidget(heading)
        note = QLabel(
            "在线模型无需下载，但需要先配置对应服务的密钥。"
            "选择后会成为歌词识别和批量识别的默认引擎。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#666")
        card_layout.addWidget(note)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(
            ["模型名称", "适用场景", "速度", "状态", "操作"]
        )
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setMinimumHeight(145)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        card_layout.addWidget(table)
        key_row = QHBoxLayout()
        key_row.addStretch()
        key_button = QPushButton("管理在线模型密钥")
        key_button.clicked.connect(lambda: self.done(self.OPEN_KEY_MANAGER))
        key_row.addWidget(key_button)
        card_layout.addLayout(key_row)
        return card, table

    def _build_card(self, title: str, description: str, category: str):
        card = QGroupBox()
        card.setObjectName(f"{category}ModelCard")
        card.setStyleSheet(
            "QGroupBox{background:white;border:1px solid #D8DEE7;border-radius:8px;"
            "margin-top:0;padding:10px}"
        )
        card_layout = QVBoxLayout(card)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:16px;font-weight:700")
        card_layout.addWidget(heading)
        note = QLabel(description)
        note.setStyleSheet("color:#666")
        note.setWordWrap(True)
        card_layout.addWidget(note)
        runtime_label = QLabel("")
        runtime_label.setWordWrap(True)
        runtime_label.setStyleSheet("font-size:11px;color:#666")
        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(
            ["模型名称", "适用场景", "速度", "质量", "大小", "状态", "操作"]
        )
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setMinimumHeight(145)
        if category == "separation":
            table.setMinimumHeight(235)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        card_layout.addWidget(table)
        return card, table, runtime_label

    @staticmethod
    def _models(category: str) -> list[CatalogModel]:
        if category == "asr":
            return list(WHISPER_MODELS)
        separation_models = [
            CatalogModel(
                "separation",
                spec.key,
                spec.name,
                spec.description,
                spec.speed,
                spec.quality,
                spec.approximate_size,
            )
            for spec in SEPARATION_MODELS.values()
        ]
        enhancement_models = [
            CatalogModel(
                "enhancement",
                spec.key,
                spec.name,
                spec.description,
                spec.speed,
                spec.quality,
                spec.approximate_size,
            )
            for spec in ENHANCEMENT_MODELS.values()
        ]
        return separation_models + enhancement_models

    @staticmethod
    def _installed(model: CatalogModel) -> bool:
        if model.category == "enhancement":
            return enhancement_model_installed(model.key)
        if model.category == "separation":
            return separation_model_installed(model.key)
        return (Path.home() / ".cache" / "whisper" / f"{model.key}.pt").is_file()

    def refresh_tables(self, *_args):
        self._fill_online_table()
        self._fill_table(self.asr_table, "asr")
        self._fill_table(self.separation_table, "separation")

    def _fill_online_table(self):
        query = self.search_input.text().strip().lower()
        models = [
            model
            for model in ONLINE_MODELS
            if not query
            or query in f"{model.name} {model.description} {model.key}".lower()
        ]
        self.online_table.setRowCount(len(models))
        for row, model in enumerate(models):
            configured = self._online_model_configured(model.key)
            active = self.config.asr.provider == model.key
            for column, value in enumerate(
                (model.name, model.description, model.speed)
            ):
                self.online_table.setItem(row, column, QTableWidgetItem(value))
            if active and configured:
                status = "正在使用 ✓"
            elif active:
                status = "当前选择 · 缺少密钥"
            else:
                status = "已配置" if configured else "缺少密钥"
            self.online_table.setItem(row, 3, QTableWidgetItem(status))
            button = QPushButton()
            button.setProperty("provider", model.key)
            if not configured:
                button.setText("配置密钥")
                button.clicked.connect(lambda: self.done(self.OPEN_KEY_MANAGER))
            else:
                button.setText("正在使用" if active else "使用")
                button.setEnabled(not active)
                button.clicked.connect(self._select_online_model)
            self.online_table.setCellWidget(row, 4, button)

    def _online_model_configured(self, provider: str) -> bool:
        if provider == "groq":
            return bool(self.config.groq_api_key)
        if provider == "xunfei":
            return self.config.has_xunfei_credentials
        return False

    def _fill_table(self, table: QTableWidget, category: str):
        query = self.search_input.text().strip().lower()
        models = [
            model
            for model in self._models(category)
            if not query
            or query in f"{model.name} {model.description} {model.key}".lower()
        ]
        table.setRowCount(len(models))
        for row, model in enumerate(models):
            values = [
                model.name,
                model.description,
                model.speed,
                model.quality,
                model.size,
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
            installed = self._installed(model)
            active = (
                category == "asr"
                and installed
                and self.config.asr.provider == "local"
                and self.config.asr.local_model == model.key
            )
            status = (
                "正在使用 ✓"
                if active
                else ("已安装 ✓" if installed else "等待下载")
            )
            table.setItem(row, 5, QTableWidgetItem(status))
            if category == "asr" and installed:
                button = QPushButton("正在使用" if active else "使用")
                button.setEnabled(not active and self._worker is None)
                button.setProperty("model", model.key)
                button.clicked.connect(self._select_local_model)
            else:
                button = QPushButton("重新下载" if installed else "下载")
                button.setEnabled(self._worker is None)
                button.clicked.connect(self._install_clicked)
            button.setProperty("category", model.category)
            button.setProperty("model", model.key)
            table.setCellWidget(row, 6, button)

    def _select_online_model(self):
        provider = self.sender().property("provider")
        if not self._online_model_configured(provider):
            self.done(self.OPEN_KEY_MANAGER)
            return
        self.config.asr.provider = provider
        self._save_config()
        display_name = next(
            (model.name for model in ONLINE_MODELS if model.key == provider),
            provider,
        )
        self.status_label.setText(f"已切换到在线模型：{display_name}。")
        self.refresh_tables()
        self.model_state_changed.emit()

    def _select_local_model(self):
        self._activate_local_model(self.sender().property("model"))

    def _activate_local_model(self, model: str):
        self.config.asr.provider = "local"
        self.config.asr.local_model = model
        self._save_config()
        self.status_label.setText(f"已切换到本地 Whisper {model}。")
        self.refresh_tables()
        self.model_state_changed.emit()

    def _save_config(self):
        config_manager.config = self.config
        config_manager.save()

    def _refresh_runtime_status(self):
        try:
            selection = select_runtime(detect_hardware())
            if selection.adapter is None:
                self.asr_runtime_label.setText("未检测到兼容 GPU，使用 CPU Worker。")
            else:
                self.asr_runtime_label.setText(
                    f"检测到 {selection.adapter.name} · 推荐 {selection.variant.runtime_id}"
                )
        except Exception as exc:
            self.asr_runtime_label.setText(f"硬件检测失败：{exc}")

        cuda_ready = separation_gpu_available()
        self.separation_gpu_check.blockSignals(True)
        if cuda_ready:
            runtime = active_separation_gpu_runtime()
            runtime_name = runtime.runtime_id if runtime else "内置 CUDA"
            self.separation_runtime_label.setText(
                f"Demucs GPU 已就绪：{runtime_name}（隔离进程调用）"
            )
            self.separation_gpu_check.setEnabled(True)
        else:
            self.separation_runtime_label.setText(
                "当前 Demucs 为 CPU 运行时；外置 ASR Worker 不能直接替代它。"
            )
            self.separation_gpu_check.setChecked(False)
            self.separation_gpu_check.setEnabled(False)
            self.config.asr.vocal_separation_use_gpu = False
        self.separation_gpu_check.blockSignals(False)

    def _save_separation_gpu_preference(self, enabled: bool):
        self.config.asr.vocal_separation_use_gpu = bool(enabled)
        self._save_config()
        self.model_state_changed.emit()

    def _save_default_separation_model(self, _index: int = -1):
        self.config.asr.vocal_separation_model = self.separation_model_combo.currentData()
        self._save_config()
        self.model_state_changed.emit()

    def _install_clicked(self):
        button = self.sender()
        self._pending_local_model = (
            button.property("model")
            if button.property("category") == "asr"
            else ""
        )
        self._worker = ModelInstallWorker(
            button.property("category"), button.property("model"), self
        )
        self._worker.progress.connect(self._show_progress)
        self._worker.finished.connect(self._install_finished)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.status_label.setText("正在准备下载…")
        self.refresh_tables()
        self._worker.start()

    def _show_progress(self, percent: int, message: str):
        self.progress.setValue(percent)
        self.status_label.setText(message)

    def _cancel_install(self):
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("正在取消…")

    def _install_finished(self, success: bool, message: str):
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(message)
        self._worker = None
        self.refresh_tables()
        if success:
            if self._pending_local_model:
                model = self._pending_local_model
                self._pending_local_model = ""
                self._activate_local_model(model)
                return
            self.model_state_changed.emit()
        elif "取消" not in message:
            QMessageBox.warning(self, "模型安装失败", message)
        self._pending_local_model = ""
