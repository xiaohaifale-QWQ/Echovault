"""Background worker for a potentially long video aggregation."""

from PyQt6.QtCore import QThread, pyqtSignal

from core.video_aggregation import aggregate_videos_by_time


class VideoAggregateWorker(QThread):
    finished = pyqtSignal(bool, object)

    def __init__(self, folder: str, offset_seconds: int, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.offset_seconds = offset_seconds

    def run(self):
        try:
            self.finished.emit(True, aggregate_videos_by_time(self.folder, self.offset_seconds))
        except Exception as exc:
            self.finished.emit(False, str(exc))
