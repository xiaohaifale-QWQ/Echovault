"""Unified local model library for Whisper ASR and Demucs separation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.model_download import DownloadCancelled, download_model
from core.vocal_separation import (
    SEPARATION_MODELS,
    SeparationCancelled,
    download_separation_model,
    separation_model_installed,
)


@dataclass(frozen=True)
class CatalogModel:
    category: str
    key: str
    name: str
    description: str
    speed: str
    quality: str
    size: str


WHISPER_MODELS = (
    CatalogModel("asr", "tiny", "Whisper Tiny", "快速预览与低配电脑", "最快", "基础", "约 144 MB"),
    CatalogModel(
        "asr",
        "base",
        "Whisper Base（推荐）",
        "日常歌词识别，速度与质量平衡",
        "快",
        "中",
        "约 139 MB",
    ),
    CatalogModel(
        "asr", "small", "Whisper Small", "更准确的多语言歌词识别", "中等", "高", "约 922 MB"
    ),
    CatalogModel(
        "asr",
        "medium",
        "Whisper Medium",
        "高精度识别，适合性能较好的电脑",
        "较慢",
        "更高",
        "约 2.85 GB",
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

            cancelled = self.isInterruptionRequested
            if self.category == "asr":
                download_model(self.model, progress=callback, cancelled=cancelled)
            else:
                download_separation_model(
                    self.model, progress=callback, cancelled=cancelled
                )
            self.finished.emit(True, "安装完成")
        except (DownloadCancelled, SeparationCancelled):
            self.finished.emit(False, "安装已取消")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class ModelLibraryDialog(QDialog):
    model_state_changed = pyqtSignal()

    def __init__(self, parent=None, *, initial_category: str = "all"):
        super().__init__(parent)
        self.setWindowTitle("模型库")
        self.resize(980, 560)
        self._worker = None
        self._active_model = None
        self._setup_ui(initial_category)
        self.refresh_table()

    def _setup_ui(self, initial_category: str):
        layout = QVBoxLayout(self)
        title = QLabel("模型库")
        title.setStyleSheet("font-size:20px;font-weight:700")
        layout.addWidget(title)
        hint = QLabel("下载完成后模型会自动出现在本地识别或人声分离的模型列表中。")
        hint.setStyleSheet("color:#666")
        layout.addWidget(hint)

        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索模型名称、场景或描述")
        self.search_input.textChanged.connect(self.refresh_table)
        toolbar.addWidget(self.search_input, 1)
        self.category_combo = QComboBox()
        self.category_combo.addItem("全部", "all")
        self.category_combo.addItem("本地识别", "asr")
        self.category_combo.addItem("人声分离", "separation")
        index = self.category_combo.findData(initial_category)
        self.category_combo.setCurrentIndex(max(index, 0))
        self.category_combo.currentIndexChanged.connect(self.refresh_table)
        toolbar.addWidget(self.category_combo)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["分类", "模型名称 / 简介", "适用场景", "速度", "质量", "大小", "状态", "操作"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#555")
        status_row.addWidget(self.status_label, 1)
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_install)
        status_row.addWidget(self.cancel_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        status_row.addWidget(close_button)
        layout.addLayout(status_row)

    @staticmethod
    def _all_models() -> list[CatalogModel]:
        models = list(WHISPER_MODELS)
        models.extend(
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
        )
        return models

    @staticmethod
    def _installed(model: CatalogModel) -> bool:
        if model.category == "separation":
            return separation_model_installed(model.key)
        return (Path.home() / ".cache" / "whisper" / f"{model.key}.pt").is_file()

    def refresh_table(self, *_args):
        query = self.search_input.text().strip().lower()
        category = self.category_combo.currentData()
        models = [
            model
            for model in self._all_models()
            if (category == "all" or model.category == category)
            and (
                not query
                or query in f"{model.name} {model.description} {model.key}".lower()
            )
        ]
        self.table.setRowCount(len(models))
        for row, model in enumerate(models):
            category_name = "本地识别" if model.category == "asr" else "人声分离"
            values = [
                category_name,
                model.name,
                model.description,
                model.speed,
                model.quality,
                model.size,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            installed = self._installed(model)
            status = QTableWidgetItem("已安装 ✓" if installed else "等待下载")
            self.table.setItem(row, 6, status)
            button = QPushButton("重新下载" if installed else "下载")
            button.setProperty("category", model.category)
            button.setProperty("model", model.key)
            button.clicked.connect(self._install_clicked)
            button.setEnabled(self._worker is None)
            self.table.setCellWidget(row, 7, button)

    def _install_clicked(self):
        button = self.sender()
        category = button.property("category")
        model = button.property("model")
        self._active_model = (category, model)
        self._worker = ModelInstallWorker(category, model, self)
        self._worker.progress.connect(self._show_progress)
        self._worker.finished.connect(self._install_finished)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.status_label.setText("正在准备下载…")
        self.refresh_table()
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
        self._active_model = None
        self.refresh_table()
        if success:
            self.model_state_changed.emit()
        elif "取消" not in message:
            QMessageBox.warning(self, "模型安装失败", message)
