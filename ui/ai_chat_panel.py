"""Dockable DeepSeek chat panel with local voice input."""
# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.ai_assistant import AISettings, chat
from core.ai_control import CLICommand, extract_cli_directives, run_cli_command
from core.asr.provider_selection import select_available_provider
from core.asr.router import get_router
from core.config import AppConfig
from core.voice_cache import new_recording_path, pcm_to_wav, voice_cache_dir


class AIChatWorker(QThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, settings: AISettings, question: str, history: list[dict[str, str]], parent=None):
        super().__init__(parent)
        self._settings = settings
        self._question = question
        self._history = history

    def run(self):
        try:
            self.completed.emit(chat(self._settings, self._question, self._history))
        except RuntimeError as exc:
            self.failed.emit(str(exc))


class VoiceTranscribeWorker(QThread):
    """Transcribe cached microphone audio, preferring a configured online engine."""

    completed = pyqtSignal(str)
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, config: AppConfig, audio_path: Path, parent=None):
        super().__init__(parent)
        self._config = config
        self._audio_path = audio_path

    def run(self):
        try:
            router = get_router(self._config)
            provider_name = select_available_provider(router)
            provider = router.get(provider_name)
            self.status.emit(f"语音输入正在使用 {provider.display_name}…")
            result = router.transcribe(
                str(self._audio_path),
                provider_name=provider_name,
                language=self._config.asr.language,
            )
            text = " ".join(segment.text.strip() for segment in result.segments if segment.text.strip())
            if not text:
                raise RuntimeError("没有识别出可用文字，请检查麦克风输入或识别引擎。")
            self.completed.emit(text)
        except (OSError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class CLICommandWorker(QThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, command: CLICommand, parent=None):
        super().__init__(parent)
        self._command = command

    def run(self):
        try:
            self.completed.emit(run_cli_command(self._command))
        except (OSError, RuntimeError) as exc:
            self.failed.emit(str(exc))


class ChatInputEdit(QTextEdit):
    """Enter sends; Ctrl+Enter intentionally keeps a line break in the prompt."""

    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        is_enter = event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
        if is_enter and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.send_requested.emit()
            event.accept()
            return
        if is_enter and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.insertPlainText("\n")
            event.accept()
            return
        super().keyPressEvent(event)


class AIChatPanel(QWidget):
    """Conversation UI that always sends the built-in manual as the system prompt."""

    command_requested = pyqtSignal(str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._history: list[dict[str, str]] = []
        self._worker: AIChatWorker | None = None
        self._voice_worker: VoiceTranscribeWorker | None = None
        self._audio_source: QAudioSource | None = None
        self._audio_device = None
        self._record_file = None
        self._raw_path: Path | None = None
        self._record_seconds = 0
        self.setMinimumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Echovault AI 助手")
        title.setStyleSheet("font-weight:bold;font-size:14px;padding:4px")
        layout.addWidget(title)

        self.messages = QTextBrowser()
        self.messages.setOpenExternalLinks(True)
        self.messages.setStyleSheet("QTextBrowser{background:#FAFAFA;border:1px solid #D9DEE5;}")
        self.messages.setHtml("<p><b>AI 助手</b></p><p>你好，我可以介绍 Echovault，并协助你使用素材库、识别、同步和命令行。</p>")
        layout.addWidget(self.messages, 1)

        self.input = ChatInputEdit()
        self.input.setPlaceholderText("输入问题，Enter 发送，Ctrl+Enter 换行")
        self.input.send_requested.connect(self._send)
        self.input.setFixedHeight(68)
        layout.addWidget(self.input)
        actions = QHBoxLayout()
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self._clear)
        actions.addWidget(self.clear_button)
        self.voice_button = QPushButton("语音输入")
        self.voice_button.setToolTip("录制语音并识别为文字；录音仅保存到本机缓存")
        self.voice_button.clicked.connect(self.toggle_voice_input)
        actions.addWidget(self.voice_button)
        actions.addStretch()
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)
        self.voice_status = QLabel("")
        self.voice_status.setStyleSheet("font-size:11px;color:#667085;padding:0 4px")
        self.voice_status.setVisible(False)
        layout.addWidget(self.voice_status)
        self._record_timer = QTimer(self)
        self._record_timer.setInterval(1000)
        self._record_timer.timeout.connect(self._update_recording_label)

    def toggle_voice_input(self):
        if self._audio_source is not None:
            self._stop_recording()
        elif self._voice_worker is None:
            self._start_recording()

    def _start_recording(self):
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self._show_voice_status("没有检测到可用麦克风。")
            return
        audio_format = QAudioFormat()
        audio_format.setSampleRate(16000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            audio_format = device.preferredFormat()
        self._raw_path = voice_cache_dir() / ".recording.pcm"
        try:
            self._record_file = self._raw_path.open("wb")
            self._audio_source = QAudioSource(device, audio_format, self)
            self._audio_device = self._audio_source.start()
            if self._audio_device is None:
                raise RuntimeError("麦克风无法开始录音。")
            self._audio_device.readyRead.connect(self._write_recording_data)
        except (OSError, RuntimeError) as exc:
            self._cleanup_recorder()
            self._show_voice_status(f"无法开始录音：{exc}")
            return
        self._record_seconds = 0
        self.voice_button.setText("停止录音 (0:00)")
        self.voice_button.setStyleSheet("color:white;background:#B64545")
        self._record_timer.start()
        self._show_voice_status("正在录音；再次点击或使用快捷键结束录音。")

    def _write_recording_data(self):
        if self._record_file is not None and self._audio_device is not None:
            self._record_file.write(bytes(self._audio_device.readAll()))

    def _stop_recording(self):
        if self._audio_source is None or self._raw_path is None:
            return
        self._write_recording_data()
        self._record_timer.stop()
        audio_format = self._audio_source.format()
        self._audio_source.stop()
        raw_path = self._raw_path
        self._cleanup_recorder()
        if not raw_path.exists() or raw_path.stat().st_size == 0:
            raw_path.unlink(missing_ok=True)
            self._show_voice_status("没有录到声音，请检查麦克风权限和输入设备。")
            return
        recording_path = new_recording_path()
        try:
            pcm_to_wav(
                raw_path,
                recording_path,
                sample_rate=audio_format.sampleRate(),
                channels=audio_format.channelCount(),
                sample_width=audio_format.bytesPerSample(),
            )
        except OSError as exc:
            self._show_voice_status(f"无法保存录音：{exc}")
            return
        finally:
            raw_path.unlink(missing_ok=True)
        self.voice_button.setEnabled(False)
        self._show_voice_status("录音已保存到本机缓存，正在识别为文字…")
        self._voice_worker = VoiceTranscribeWorker(self.config, recording_path, self)
        self._voice_worker.status.connect(self._show_voice_status)
        self._voice_worker.completed.connect(self._on_voice_transcribed)
        self._voice_worker.failed.connect(self._on_voice_failed)
        self._voice_worker.start()

    def _cleanup_recorder(self):
        if self._record_file is not None:
            self._record_file.close()
        self._record_file = None
        self._audio_device = None
        if self._audio_source is not None:
            self._audio_source.deleteLater()
        self._audio_source = None
        self._raw_path = None
        self.voice_button.setText("语音输入")
        self.voice_button.setStyleSheet("")

    def _update_recording_label(self):
        self._record_seconds += 1
        minutes, seconds = divmod(self._record_seconds, 60)
        self.voice_button.setText(f"停止录音 ({minutes}:{seconds:02d})")

    def _on_voice_transcribed(self, text: str):
        existing = self.input.toPlainText().strip()
        self.input.setPlainText(f"{existing}\n{text}" if existing else text)
        self._finish_voice_input("已将语音识别为文字，正在发送给 AI…")
        self._send()

    def _on_voice_failed(self, message: str):
        self._finish_voice_input(f"语音识别失败：{message}")

    def _finish_voice_input(self, message: str):
        if self._voice_worker is not None:
            self._voice_worker.deleteLater()
            self._voice_worker = None
        self.voice_button.setEnabled(True)
        self._show_voice_status(message)

    def _show_voice_status(self, message: str):
        self.voice_status.setText(message)
        self.voice_status.setVisible(True)

    def _settings(self) -> AISettings:
        from core.ai_assistant import settings_from_config

        return settings_from_config(self.config)

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    def _append(self, speaker: str, message: str):
        self.messages.append(f"<p><b>{speaker}</b><br>{self._escape(message)}</p>")
        self.messages.verticalScrollBar().setValue(self.messages.verticalScrollBar().maximum())

    def _send(self):
        question = self.input.toPlainText().strip()
        if not question or self._worker is not None:
            return
        self.input.clear()
        self._append("你", question)
        self.send_button.setEnabled(False)
        self._worker = AIChatWorker(self._settings(), question, list(self._history), self)
        self._worker.completed.connect(lambda answer: self._on_answer(question, answer))
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_answer(self, question: str, answer: str):
        displayed_answer, commands = extract_cli_directives(answer)
        self._history.extend(({"role": "user", "content": question}, {"role": "assistant", "content": answer}))
        self._append("AI", displayed_answer or "我正在执行软件操作。")
        for command in commands:
            self.command_requested.emit(command)
        self._finish_request()

    def append_command_result(self, message: str):
        self._append("软件控制", message)

    def _on_error(self, message: str):
        self._append("AI", f"请求失败：{message}")
        self._finish_request()

    def _finish_request(self):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        self.send_button.setEnabled(True)

    def _clear(self):
        self._history.clear()
        self.messages.setHtml("<p><b>AI 助手</b></p><p>对话已清空，使用手册与系统提示词仍会在每次请求中发送。</p>")
