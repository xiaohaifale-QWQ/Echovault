"""
后台转录 Worker

在 QThread 中执行 ASR 识别，避免阻塞 UI。
"""

from PyQt6.QtCore import QThread, pyqtSignal

from core.config import AppConfig
from core.asr.router import ASRRouter
from core.lrc_writer import transcribe_and_save_lrc


class TranscribeWorker(QThread):
    """后台转录线程"""
    
    progress = pyqtSignal(int, int, str)     # current, total, filename
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
            filename = file_path.split("\\")[-1] if "\\" in file_path else file_path.split("/")[-1]
            
            self.progress.emit(i, total, filename)
            
            try:
                lrc_path = transcribe_and_save_lrc(
                    audio_path=file_path,
                    router=self.router,
                    language=self.config.asr.language,
                    output_dir=self.config.output_lrc_dir,
                    overwrite=True,
                )
                self._results[file_path] = {"success": True, "lrc_path": lrc_path, "error": None}
                self.song_done.emit(file_path, lrc_path, True)
                
            except Exception as e:
                self._results[file_path] = {"success": False, "lrc_path": None, "error": str(e)}
                self.song_done.emit(file_path, "", False)
        
        self.finished.emit(self._results)
