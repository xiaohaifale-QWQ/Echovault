"""
MusicSync 主窗口

三栏布局：
- 左侧：音乐库文件夹树
- 中间：歌曲列表 + 状态
- 右侧：详情/同步（选项卡切换）

菜单栏：文件 / 识别 / 同步 / 设置 / 帮助
状态栏：歌曲统计 + 上次同步时间
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QMenuBar, QMenu, QStatusBar,
    QMessageBox, QFileDialog, QLabel, QWidget, QVBoxLayout,
    QTabWidget, QPushButton, QProgressBar,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QIcon

from core.config import config_manager, AppConfig
from core.asr.router import ASRRouter, get_router
from core.audio_utils import is_supported, SUPPORTED_FORMATS

from ui.library_panel import LibraryPanel
from ui.song_list_panel import SongListPanel
from ui.detail_panel import DetailPanel
from ui.settings_dialog import SettingsDialog
from ui.sync_panel import SyncPanel


class MainWindow(QMainWindow):
    """主窗口"""
    
    # 信号：请求转录音频文件
    transcribe_requested = pyqtSignal(str)  # 文件路径
    
    def __init__(self):
        super().__init__()
        
        self.config = config_manager.load()
        self.router = get_router(self.config)
        
        self._setup_ui()
        self._setup_menubar()
        self._setup_statusbar()
        self._connect_signals()
        
        # 恢复上次的音乐目录
        if self.config.music_dirs:
            self.library_panel.set_root(self.config.music_dirs[0])
    
    def _setup_ui(self):
        """初始化 UI 布局"""
        self.setWindowTitle("MusicSync — AI 歌词识别")
        self.setMinimumSize(QSize(1100, 680))
        self.resize(QSize(1280, 780))
        
        # 中央三栏布局
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：音乐库
        self.library_panel = LibraryPanel()
        splitter.addWidget(self.library_panel)
        
        # 中间：歌曲列表
        self.song_list_panel = SongListPanel()
        splitter.addWidget(self.song_list_panel)
        
        # 右侧：详情 + 同步（选项卡切换）
        self.right_tabs = QTabWidget()
        
        self.detail_panel = DetailPanel()
        self.right_tabs.addTab(self.detail_panel, "详情")
        
        self.sync_panel = SyncPanel()
        self.right_tabs.addTab(self.sync_panel, "同步")
        
        splitter.addWidget(self.right_tabs)
        
        # 比例：1 : 2 : 1.5
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([250, 500, 380])
        
        self.setCentralWidget(splitter)
    
    def _setup_menubar(self):
        """菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        open_dir_action = QAction("打开音乐文件夹(&O)...", self)
        open_dir_action.setShortcut("Ctrl+O")
        open_dir_action.triggered.connect(self._on_open_folder)
        file_menu.addAction(open_dir_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 识别菜单
        trans_menu = menubar.addMenu("识别(&T)")
        
        trans_all_action = QAction("识别全部未标注歌曲(&A)", self)
        trans_all_action.setShortcut("Ctrl+Shift+A")
        trans_all_action.triggered.connect(self._on_transcribe_all)
        trans_menu.addAction(trans_all_action)
        
        trans_selected_action = QAction("识别选中歌曲(&S)", self)
        trans_selected_action.setShortcut("Ctrl+T")
        trans_selected_action.triggered.connect(self._on_transcribe_selected)
        trans_menu.addAction(trans_selected_action)
        
        # 同步菜单
        sync_menu = menubar.addMenu("同步(&Y)")
        
        sync_goto_action = QAction("打开同步面板(&S)", self)
        sync_goto_action.setShortcut("Ctrl+D")
        sync_goto_action.triggered.connect(lambda: self.right_tabs.setCurrentIndex(1))
        sync_menu.addAction(sync_goto_action)
        
        # 设置菜单
        settings_menu = menubar.addMenu("设置(&S)")
        
        settings_action = QAction("偏好设置(&P)...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._on_settings)
        settings_menu.addAction(settings_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_statusbar(self):
        """状态栏"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        self.status_label = QLabel("就绪")
        self.statusbar.addWidget(self.status_label)
        
        self.trans_progress = QProgressBar()
        self.trans_progress.setMaximumWidth(250)
        self.trans_progress.setMaximumHeight(16)
        self.trans_progress.setVisible(False)
        self.statusbar.addWidget(self.trans_progress)
        
        self.count_label = QLabel("")
        self.statusbar.addPermanentWidget(self.count_label)
        
        self.provider_label = QLabel("")
        self.statusbar.addPermanentWidget(self.provider_label)
        
        self._refresh_statusbar()
    
    def _refresh_statusbar(self):
        """刷新状态栏信息"""
        songs = self.song_list_panel.get_all_songs()
        has_lrc = sum(1 for s in songs if s.get("has_lrc"))
        total = len(songs)
        
        self.count_label.setText(f"共 {total} 首 | 有歌词 {has_lrc} 首")
        
        available = self.router.list_available()
        if available:
            self.provider_label.setText(f"Provider: {available[0].display_name}")
        else:
            self.provider_label.setText("Provider: 无可用 (需安装 Groq 或 Whisper)")
    
    def _connect_signals(self):
        """连接信号"""
        # 文件夹树 → 歌曲列表
        self.library_panel.folder_selected.connect(self._on_folder_selected)
        
        # 歌曲列表 → 详情面板
        self.song_list_panel.song_selected.connect(self.detail_panel.show_song)
        
        # 详情面板 → 请求识别
        self.detail_panel.transcribe_clicked.connect(self._on_transcribe_single)
        self.detail_panel.edit_lyrics_clicked.connect(self._on_edit_lyrics)
        
        # 刷新计数
        self.song_list_panel.model_updated.connect(self._refresh_statusbar)
        
        # 折叠音乐库
        self.song_list_panel.toggle_library.connect(self._toggle_library)
        self._library_visible = True
    
    def _toggle_library(self):
        self._library_visible = not self._library_visible
        self.library_panel.setVisible(self._library_visible)
        self.song_list_panel.btn_lib.setText("\u2630" if self._library_visible else "\u00D7")
    
    # ─── 事件处理 ─────────────────────────────
    
    def _on_open_folder(self):
        """选择音乐文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择音乐文件夹",
            self.config.music_dirs[0] if self.config.music_dirs else str(Path.home() / "Music"),
        )
        if dir_path:
            self.library_panel.set_root(dir_path)
            self.config.music_dirs = [dir_path]
            config_manager.save()
    
    def _on_folder_selected(self, folder_path: str):
        """文件夹被选中 → 扫描歌曲加载到列表"""
        self.status_label.setText(f"扫描中: {folder_path}...")
        
        audio_files = []
        for ext in SUPPORTED_FORMATS:
            audio_files.extend(
                str(p) for p in Path(folder_path).rglob(f"*{ext}")
            )
        
        songs = []
        for f in sorted(audio_files):
            pf = Path(f)
            lrc_path = pf.with_suffix(".lrc")
            songs.append({
                "path": f,
                "name": pf.name,
                "folder": str(pf.parent.relative_to(folder_path)) if pf.parent != Path(folder_path) else "",
                "size": pf.stat().st_size,
                "has_lrc": lrc_path.exists(),
                "lrc_path": str(lrc_path) if lrc_path.exists() else None,
            })
        
        self.song_list_panel.load_songs(songs)
        self._refresh_statusbar()
        
        # 同步面板也设置本机路径
        self.sync_panel.set_dir_a(folder_path)
        
        self.status_label.setText("就绪")
    
    def _on_transcribe_single(self, file_path: str):
        """识别单首歌"""
        self._run_transcription([file_path])
    
    def _on_transcribe_selected(self):
        """识别选中的歌曲"""
        selected = self.song_list_panel.get_selected_songs()
        if not selected:
            QMessageBox.information(self, "提示", "请先在歌曲列表中选中要识别的歌曲。")
            return
        files = [s["path"] for s in selected if not s.get("has_lrc")]
        if not files:
            QMessageBox.information(self, "提示", "选中的歌曲都已有歌词。")
            return
        self._run_transcription(files)
    
    def _on_transcribe_all(self):
        """识别全部未标注歌曲"""
        songs = self.song_list_panel.get_all_songs()
        files = [s["path"] for s in songs if not s.get("has_lrc")]
        if not files:
            QMessageBox.information(self, "提示", "所有歌曲都已有歌词！")
            return
        
        reply = QMessageBox.question(
            self, "确认", f"将为 {len(files)} 首歌曲识别歌词，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_transcription(files)
    
    def _run_transcription(self, files: list[str]):
        """执行批量识别"""
        from ui.transcribe_worker import TranscribeWorker
        
        if not self.router.list_available():
            msg = "没有可用的语音识别引擎。\n\n"
            try: import groq
            except ImportError: msg += "- Groq SDK 未安装: pip install groq\n"
            else: msg += "- Groq API Key 未设置\n"
            try: import whisper
            except ImportError: msg += "- 本地 Whisper 未安装: pip install openai-whisper\n"
            QMessageBox.warning(self, "无可用 Provider", msg)
            self._on_settings()
            return
        
        self.worker = TranscribeWorker(files, self.router, self.config)
        self.worker.progress.connect(self._on_transcribe_progress)
        self.worker.finished.connect(self._on_transcribe_finished)
        self.worker.song_done.connect(self._on_song_done)
        
        self.trans_progress.setVisible(True)
        self.trans_progress.setMaximum(len(files))
        self.trans_progress.setValue(0)
        self.status_label.setText(f"识别中... 0/{len(files)}")
        self.worker.start()
    
    def _on_transcribe_progress(self, current: int, total: int, filename: str):
        self.trans_progress.setValue(current)
        self.status_label.setText(f"识别中... {current}/{total} - {filename}")
    
    def _on_song_done(self, file_path: str, lrc_path: str, success: bool):
        self.song_list_panel.update_song_status(file_path, success)
        self._refresh_statusbar()
    
    def _on_transcribe_finished(self, results: dict):
        self.trans_progress.setVisible(False)
        success = sum(1 for v in results.values() if v["success"])
        failed = len(results) - success
        self.status_label.setText(f"识别完成: 成功 {success}, 失败 {failed}")
        self._refresh_statusbar()
        
        if failed > 0:
            QMessageBox.warning(
                self, "识别完成",
                f"成功: {success} 首\n失败: {failed} 首\n\n请检查网络连接或 API Key 配置。"
            )
    
    def _on_edit_lyrics(self, file_path: str):
        """打开歌词编辑器"""
        from ui.lyrics_editor import LyricsEditorDialog
        
        lrc_path = str(Path(file_path).with_suffix(".lrc"))
        dialog = LyricsEditorDialog(file_path, lrc_path, self)
        dialog.exec()
        
        # 编辑器关闭后刷新状态
        has_lrc = os.path.exists(lrc_path)
        self.song_list_panel.update_song_status(file_path, has_lrc)
        self._refresh_statusbar()
    
    def _on_settings(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            # 设置已保存，重建 router
            self.router = get_router(self.config)
            self._refresh_statusbar()
    
    def _on_about(self):
        """关于对话框"""
        QMessageBox.about(
            self, "关于 MusicSync",
            "<h3>MusicSync</h3>"
            "<p>AI 歌词识别 + 文件同步</p>"
            "<p>版本: 0.1.0 (Phase 1)</p>"
            "<hr>"
            "<p>技术栈: Python + PyQt6 + Whisper</p>"
            "<p>ASR: Groq Whisper / OpenAI Whisper</p>"
        )
