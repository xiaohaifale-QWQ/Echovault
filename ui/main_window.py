"""
琳琅乐府 主窗口

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
from core.environment import build_environment_report
from services.library_service import scan_audio

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

        report = build_environment_report(self.config)
        if not report["ffmpeg"]["available"]:
            self.status_label.setText("未检测到 ffmpeg，歌词识别暂不可用")
    
    def _setup_ui(self):
        """初始化 UI 布局"""
        self.setWindowTitle("琳琅乐府 — AI 歌词识别")
        self.setMinimumSize(QSize(1100, 680))
        self.resize(QSize(1280, 780))
        
        # 两栏布局
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：歌曲列表
        self.song_list_panel = SongListPanel()
        splitter.addWidget(self.song_list_panel)
        
        # 右侧：选项卡
        self.right_tabs = QTabWidget()
        
        self.detail_panel = DetailPanel()
        self.right_tabs.addTab(self.detail_panel, "详情")
        
        self.library_panel = LibraryPanel()
        self.right_tabs.addTab(self.library_panel, "音乐库")
        
        self.sync_panel = SyncPanel()
        self.right_tabs.addTab(self.sync_panel, "同步")
        
        splitter.addWidget(self.right_tabs)
        
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([700, 400])
        
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
        sync_goto_action.triggered.connect(lambda: self.right_tabs.setCurrentIndex(2))
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
        self.trans_progress.setMaximumWidth(200)
        self.trans_progress.setMaximumHeight(16)
        self.trans_progress.setVisible(False)
        self.statusbar.addWidget(self.trans_progress)

        self.total_trans_progress = QProgressBar()
        self.total_trans_progress.setMaximumWidth(200)
        self.total_trans_progress.setMaximumHeight(16)
        self.total_trans_progress.setVisible(False)
        self.statusbar.addWidget(self.total_trans_progress)
        
        self.btn_stop_transcribe = QPushButton("停止")
        self.btn_stop_transcribe.setMaximumHeight(18)
        self.btn_stop_transcribe.setStyleSheet("QPushButton{color:#c0392b;font-size:11px;padding:0 6px;margin-left:4px}QPushButton:hover{color:white;background:#c0392b}")
        self.btn_stop_transcribe.setVisible(False)
        self.btn_stop_transcribe.clicked.connect(self._on_stop_transcribe)
        self.statusbar.addWidget(self.btn_stop_transcribe)
        
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
        
        provider = self.router.get(self.config.asr.provider)
        if provider and provider.is_available():
            self.provider_label.setText(f"引擎: {provider.display_name}")
        else:
            self.provider_label.setText("引擎: 不可用 (请检查设置)")
    
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
        
        # 批量识别按钮
        self.song_list_panel.batch_transcribe.connect(self._on_transcribe_all)
        
        self._refresh_statusbar()
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
        
        songs = scan_audio(folder_path)
        
        self.song_list_panel.load_songs(songs, root_dir=folder_path)
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
        files = [s["path"] for s in songs if not s.get("has_lrc") and not s.get("instrumental")]
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
        
        # 检查当前配置的 Provider 是否可用
        provider_name = self.config.asr.provider
        provider = self.router.get(provider_name)
        
        if not provider or not provider.is_available():
            if provider_name == "groq":
                msg = "Groq 云端引擎不可用。\n\n请确认已设置 Groq API Key。\n免费获取: https://console.groq.com/keys"
            elif provider_name == "local":
                msg = "本地 Whisper 引擎不可用。\n\n"
                try: import whisper
                except ImportError: msg += "- openai-whisper 未安装: pip install openai-whisper\n"
                else: msg += "- 模型未下载，请在设置中下载模型\n"
            else:
                msg = f"引擎 '{provider_name}' 不可用。"
            QMessageBox.warning(self, "引擎不可用", msg)
            self._on_settings()
            return
        
        self.worker = TranscribeWorker(files, self.router, self.config)
        self.worker.progress.connect(self._on_transcribe_progress)
        self.worker.song_progress.connect(self._on_song_progress)
        self.worker.stage_progress.connect(self._on_stage_progress)
        self.worker.finished.connect(self._on_transcribe_finished)
        self.worker.song_done.connect(self._on_song_done)
        
        self.btn_stop_transcribe.setVisible(True)
        self.trans_progress.setVisible(True)
        self.trans_progress.setRange(0, 100)
        self.trans_progress.setFormat("本首进度 %p%")
        self.total_trans_progress.setVisible(len(files) > 1)
        self.total_trans_progress.setRange(0, 100)
        self.total_trans_progress.setFormat("总进度 %p%")
        self.total_trans_progress.setValue(0)
        self.trans_progress.setValue(0)
        self.status_label.setText(f"识别中... 0/{len(files)}")
        self.worker.start()
    
    def _on_transcribe_progress(self, current: int, total: int, filename: str):
        self.status_label.setText(f"识别中... {current}/{total} - {filename}")

    def _on_song_progress(
        self,
        current: int,
        total: int,
        song_percent: int,
        filename: str,
        message: str,
        chunk_index: int,
        chunk_total: int,
    ):
        self.trans_progress.setValue(song_percent)
        if total > 1:
            overall = int(((current - 1) + song_percent / 100) / total * 100)
            self.total_trans_progress.setValue(overall)
        chunk = f" · 第 {chunk_index}/{chunk_total} 段" if chunk_total else ""
        self.status_label.setText(f"{message}{chunk}")
    
    def _on_stage_progress(self, msg: str):
        self.status_label.setText(msg)
    
    def _on_stop_transcribe(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.requestInterruption()
            self.btn_stop_transcribe.setEnabled(False)
            self.status_label.setText("正在停止...")
    
    def _on_song_done(self, file_path: str, lrc_path: str, success: bool):
        self.song_list_panel.update_song_status(file_path, success)
        # 识别成功后立即刷新右侧详情面板
        if success:
            songs = self.song_list_panel.get_all_songs()
            for s in songs:
                if s["path"] == file_path:
                    self.detail_panel.show_song(s)
                    break
        # 自动检测纯音乐：歌词太短（<20字）可能是纯音乐
        if success and lrc_path and os.path.exists(lrc_path):
            try:
                text = Path(lrc_path).read_text(encoding="utf-8")
                # 提取所有歌词文本（去掉时间戳和元数据）
                import re
                lyric_text = "".join(re.findall(r'\](\S.*)', text))
                chars = len(lyric_text.replace(" ", ""))
                if chars < 20:
                    self.song_list_panel.mark_instrumental(file_path, auto=True)
                    self.status_label.setText(f"检测到疑似纯音乐: {Path(file_path).name} ({chars}字)")
            except: pass
        self._refresh_statusbar()
    
    def _on_transcribe_finished(self, results: dict):
        self.btn_stop_transcribe.setVisible(False)
        self.btn_stop_transcribe.setEnabled(True)
        self.trans_progress.setVisible(False)
        self.total_trans_progress.setVisible(False)
        self.trans_progress.setRange(0, 100)  # 恢复正常模式
        self.trans_progress.setValue(0)
        success = sum(1 for v in results.values() if v["success"])
        failed = len(results) - success
        self.status_label.setText(f"识别完成: 成功 {success}, 失败 {failed}")
        self._refresh_statusbar()
        
        if failed > 0:
            # 收集实际的错误信息
            errors = []
            for fp, r in results.items():
                if not r["success"] and r.get("error"):
                    err = str(r["error"])
                    if err not in errors:
                        errors.append(err)
            err_detail = "\n".join(errors[:3])  # 最多显示 3 条
            if len(errors) > 3:
                err_detail += f"\n... 还有 {len(errors)-3} 条"
            
            provider_name = self.config.asr.provider
            if provider_name == "local":
                hint = "请确认已在设置中下载模型，且 ffmpeg 已安装。"
            elif provider_name == "groq":
                hint = "请检查网络连接和 Groq API Key 配置。"
            else:
                hint = "请检查相关配置。"
            
            QMessageBox.warning(
                self, "识别完成",
                f"成功: {success} 首\n失败: {failed} 首\n\n{err_detail}\n\n{hint}"
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
        result = dialog.exec()
        if result == 42:
            # GPU 安装完成，重启应用
            import logging
            logging.getLogger("linlangyuefu").info("GPU 安装完成，准备重启...")
            self._do_restart()
        elif result:
            # 设置已保存，重建 router
            self.router = get_router(self.config)
            self._refresh_statusbar()
    
    def _do_restart(self):
        """重新启动应用"""
        import logging
        import os
        import subprocess
        import sys

        if getattr(sys, "frozen", False):
            # PyInstaller directory builds have no adjacent main.py. Relaunch the
            # executable itself instead of trying to invoke a nonexistent script.
            cmd = [sys.executable]
            cwd = os.path.dirname(sys.executable)
        else:
            script = os.path.abspath(sys.argv[0])
            cmd = [sys.executable, script]
            cwd = os.path.dirname(script)
        logging.getLogger("linlangyuefu").info(f"重启: {cmd}")
        try:
            subprocess.Popen(
                cmd,
                cwd=cwd,
                creationflags=0x00000008 if sys.platform == "win32" else 0,
            )
            logging.getLogger("linlangyuefu").info("新进程已启动，退出旧进程")
        except Exception as e:
            logging.getLogger("linlangyuefu").error(f"重启失败: {e}")
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
    
    def _on_about(self):
        """关于对话框"""
        QMessageBox.about(
            self, "关于 琳琅乐府",
            "<h3>琳琅乐府</h3>"
            "<p>AI 歌词识别 + 文件同步</p>"
            "<p>版本: 0.1.0 (Phase 1)</p>"
            "<hr>"
            "<p>技术栈: Python + PyQt6 + Whisper</p>"
            "<p>ASR: Groq Whisper / OpenAI Whisper</p>"
        )
