"""
后台转录 Worker

在 QThread 中执行 ASR 识别，避免阻塞 UI。
"""

from PyQt6.QtCore import QThread, pyqtSignal

from core.config import AppConfig
from core.asr.router import ASRRouter
from core.lrc_writer import transcribe_and_save_lrc
from core.recognition_progress import RecognitionProgress


class TranscribeWorker(QThread):
    """后台转录线程"""
    
    progress = pyqtSignal(int, int, str)     # current, total, filename
    song_progress = pyqtSignal(int, int, int, str, str, int, int)
    stage_progress = pyqtSignal(str)          # 当前阶段描述
    song_done = pyqtSignal(str, str, bool)    # file_path, lrc_path, success
    finished = pyqtSignal(dict)               # {file_path: {"success": bool, "lrc_path": str, "error": str}}
    
    def __init__(self, files: list[str], router: ASRRouter, config: AppConfig, parent=None):
        super().__init__(parent)
        self.files = files
        self.router = router
        self.config = config
        self._results = {}
    
    def run(self):
        """在后台线程中执行"""
        total = len(self.files)
        
        for i, file_path in enumerate(self.files, 1):
            if self.isInterruptionRequested():
                self.stage_progress.emit("已停止")
                break
            
            filename = file_path.split("\\")[-1] if "\\" in file_path else file_path.split("/")[-1]
            
            self.progress.emit(i, total, filename)
            
            prefix = f"[{i}/{total}] " if total > 1 else ""
            def on_stage(event: RecognitionProgress):
                self.song_progress.emit(
                    i,
                    total,
                    event.percent,
                    filename,
                    event.message,
                    event.chunk_index,
                    event.chunk_total,
                )
                self.stage_progress.emit(f"{prefix}{event.message}")
            
            try:
                lrc_path = transcribe_and_save_lrc(
                    audio_path=file_path,
                    router=self.router,
                    language=self.config.asr.language,
                    output_dir=self.config.output_lrc_dir,
                    overwrite=True,
                    progress_callback=on_stage,
                )
                self._results[file_path] = {"success": True, "lrc_path": lrc_path, "error": None}
                self.song_done.emit(file_path, lrc_path, True)
                
            except Exception as e:
                self._results[file_path] = {"success": False, "lrc_path": None, "error": str(e)}
                self.song_done.emit(file_path, "", False)
        
        self.finished.emit(self._results)
