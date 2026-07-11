"""Settings dialog with local model download"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QCheckBox, QPushButton,
    QGroupBox, QLabel, QDialogButtonBox, QFileDialog, QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from core.config import AppConfig, config_manager


class _DownloadWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, model: str):
        super().__init__(); self.model = model

    def run(self):
        try:
            self.progress.emit(f"Downloading {self.model}...")
            import whisper
            whisper.load_model(self.model)
            self.finished.emit(True, f"{self.model} ready")
        except Exception as e:
            self.finished.emit(False, str(e))


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent); self.config = config
        self._setup_ui(); self._load_config()

    def _setup_ui(self):
        self.setWindowTitle("Preferences"); self.setMinimumWidth(500)
        l = QVBoxLayout(self)

        ag = QGroupBox("ASR"); af = QFormLayout(ag)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Groq Whisper (cloud, free)", "groq")
        self.provider_combo.addItem("Local Whisper (offline)", "local")
        self.provider_combo.currentIndexChanged.connect(self._on_prov)
        af.addRow("Engine:", self.provider_combo)

        self.api_input = QLineEdit(); self.api_input.setPlaceholderText("API Key...")
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password); af.addRow("Groq Key:", self.api_input)
        kh = QLabel('<a href="https://console.groq.com/keys" style="color:#1976D2">Get free key</a>')
        kh.setOpenExternalLinks(True); kh.setStyleSheet("font-size:11px;margin-left:4px"); af.addRow("", kh)

        self.lang_combo = QComboBox()
        for t, v in [("Auto", None), ("Chinese", "zh"), ("English", "en"), ("Japanese", "ja"), ("Korean", "ko")]:
            self.lang_combo.addItem(t, v)
        af.addRow("Language:", self.lang_combo)

        self.model_combo = QComboBox()
        for t, v in [("tiny (39M)", "tiny"), ("base (74M)", "base"), ("small (244M)", "small"), ("medium (769M)", "medium")]:
            self.model_combo.addItem(t, v)
        self.model_combo.setVisible(False); af.addRow("Model:", self.model_combo)

        dl_row = QHBoxLayout()
        self.btn_dl = QPushButton("Download Model"); self.btn_dl.setVisible(False)
        self.btn_dl.clicked.connect(self._on_download); dl_row.addWidget(self.btn_dl)
        self.dl_bar = QProgressBar(); self.dl_bar.setVisible(False); self.dl_bar.setMaximum(0)
        dl_row.addWidget(self.dl_bar); dl_row.addStretch()
        af.addRow("", dl_row)

        self.vocal_check = QCheckBox("Demucs vocal separation (1-3 min/song)")
        af.addRow("", self.vocal_check)
        l.addWidget(ag)

        lg = QGroupBox("Lyrics Output"); lf = QFormLayout(lg)
        dr = QHBoxLayout(); self.lrc_input = QLineEdit()
        self.lrc_input.setPlaceholderText("same as audio folder"); dr.addWidget(self.lrc_input)
        bb = QPushButton("..."); bb.clicked.connect(lambda: self._browse(self.lrc_input)); dr.addWidget(bb)
        lf.addRow("LRC dir:", dr); l.addWidget(lg)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save); btns.rejected.connect(self.reject); l.addWidget(btns)

    def _load_config(self):
        c = self.config
        self.provider_combo.setCurrentIndex(0 if c.asr.provider == "groq" else 1)
        self.api_input.setText(c.groq_api_key)
        self.lang_combo.setCurrentIndex(max(0, [i for i in range(self.lang_combo.count()) if self.lang_combo.itemData(i) == c.asr.language][0]) if c.asr.language else 0)
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

    def _on_download(self):
        model = self.model_combo.currentData()
        self.btn_dl.setEnabled(False); self.dl_bar.setVisible(True)
        self.worker = _DownloadWorker(model)
        self.worker.progress.connect(lambda m: self.dl_bar.setFormat(m))
        self.worker.finished.connect(self._on_dl_done)
        self.worker.start()

    def _on_dl_done(self, ok, msg):
        self.btn_dl.setEnabled(True); self.dl_bar.setVisible(False)
        if ok:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Done", msg)
        else:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Download failed:\n{msg}")

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Choose")
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
