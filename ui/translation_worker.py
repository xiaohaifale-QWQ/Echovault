"""Background worker for single and batch LRC translation."""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.ai_assistant import settings_from_config
from core.lyrics_translation import translate_lrc_file


class TranslationWorker(QThread):
    progress = pyqtSignal(int, int, str)
    stage = pyqtSignal(int, int, str, str, int)
    finished = pyqtSignal(dict)

    def __init__(
        self,
        lrc_paths: list[str],
        *,
        engine: str,
        source_language: str,
        target_language: str,
        config,
        parent=None,
    ):
        super().__init__(parent)
        self.lrc_paths = lrc_paths
        self.engine = engine
        self.source_language = source_language
        self.target_language = target_language
        self.config = config

    def run(self):
        results = {}
        ai_settings = settings_from_config(self.config) if self.engine == "ai" else None
        total = len(self.lrc_paths)
        for index, lrc_path in enumerate(self.lrc_paths, start=1):
            if self.isInterruptionRequested():
                break
            filename = Path(lrc_path).name
            self.progress.emit(index, total, filename)
            source_text = "自动检测语言" if self.source_language == "auto" else self.source_language
            self.stage.emit(index, total, filename, f"正在{source_text}并读取歌词…", 10)
            try:
                engine_name = "AI 接口" if self.engine == "ai" else "本地翻译库"
                self.stage.emit(index, total, filename, f"正在调用{engine_name}…", 35)
                output = translate_lrc_file(
                    lrc_path,
                    engine=self.engine,
                    source_language=self.source_language,
                    target_language=self.target_language,
                    ai_settings=ai_settings,
                )
                results[lrc_path] = {"success": True, "output": str(output)}
                self.stage.emit(
                    index, total, filename, f"已生成 {Path(output).name}", 100
                )
            except Exception as exc:
                results[lrc_path] = {"success": False, "error": str(exc)}
                self.stage.emit(index, total, filename, f"失败：{exc}", 100)
        self.finished.emit(results)
