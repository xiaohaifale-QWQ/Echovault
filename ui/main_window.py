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
    QTabWidget, QPushButton, QProgressBar, QStackedWidget,
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut

from core.config import config_manager, AppConfig
from core.asr.router import ASRRouter, get_router
from core.environment import build_environment_report
from core.resource_monitor import format_resource_usage, sample_resource_usage
from services.library_service import scan_audio
from core.video_library import scan_videos
from core.video_aggregation import write_video_transcript_timeline

from ui.library_panel import LibraryPanel
from ui.lyrics_preview_panel import LyricsPreviewPanel
from ui.song_list_panel import SongListPanel
from ui.detail_panel import DetailPanel
from ui.settings_dialog import SettingsDialog
from ui.key_manager_dialog import KeyManagerDialog
from ui.help_dialog import HelpDialog
from ui.ai_chat_panel import AIChatPanel, CLICommandWorker
from ui.batch_operations_panel import BatchOnlineLyricsWorker, BatchOperationsPanel
from ui.online_lyrics_panel import OnlineLyricsPanel, LyricsCalibrationWorker
from core.ai_control import validate_cli_command
from ui.sync_panel import SyncPanel


class MainWindow(QMainWindow):
    """主窗口"""
    
    # 信号：请求转录音频文件
    transcribe_requested = pyqtSignal(str)  # 文件路径
    
    def __init__(self):
        super().__init__()
        
        self.config = config_manager.load()
        self.router = get_router(self.config)
        self._selected_material_folder = ""
        
        self._setup_ui()
        self._setup_menubar()
        self._setup_statusbar()
        self._connect_signals()
        self._voice_shortcut = QShortcut(self)
        self._voice_shortcut.activated.connect(self._toggle_voice_input_shortcut)
        self._configure_voice_input_shortcut()
        
        self.library_panel.set_directories(self.config.music_dirs, self.config.video_dirs)
        self.library_panel.set_select_all_modes(
            self.config.music_select_all, self.config.video_select_all
        )
        if self.config.music_dirs:
            self._on_folder_selected(self.config.music_dirs[0])

        report = build_environment_report(self.config)
        if not report["ffmpeg"]["available"]:
            self.status_label.setText("未检测到 ffmpeg，歌词识别暂不可用")
    
    def _setup_ui(self):
        """初始化 UI 布局"""
        self.setWindowTitle("琳琅乐府 — AI 歌词识别")
        self.setMinimumSize(QSize(1100, 680))
        self.resize(QSize(1280, 780))
        
        # 中间/右侧内容区。启用 AI 后，外层会在其左侧固定一栏聊天面板。
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter = splitter
        
        # 左侧：素材列表
        self.song_list_panel = SongListPanel()
        self.lyrics_preview_panel = LyricsPreviewPanel()
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self.song_list_panel)
        self.left_stack.addWidget(self.lyrics_preview_panel)
        splitter.addWidget(self.left_stack)
        
        # 右侧：选项卡
        self.right_tabs = QTabWidget()
        
        self.detail_panel = DetailPanel(self.config)
        self.right_tabs.addTab(self.detail_panel, "详情")
        
        self.library_panel = LibraryPanel()
        self.right_tabs.addTab(self.library_panel, "素材库")

        self.online_lyrics_panel = OnlineLyricsPanel()
        self.right_tabs.addTab(self.online_lyrics_panel, "在线匹配")

        self.batch_operations_panel = BatchOperationsPanel(self.config)
        self.right_tabs.addTab(self.batch_operations_panel, "批量处理")

        self.sync_panel = SyncPanel()
        self.right_tabs.addTab(self.sync_panel, "同步")
        
        splitter.addWidget(self.right_tabs)
        
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([700, 400])
        
        self._ai_panel_width = 340
        self._ai_mode_enabled = False
        self.ai_chat_panel = AIChatPanel(self.config)
        self.ai_chat_panel.setFixedWidth(self._ai_panel_width)
        self.ai_chat_panel.setVisible(False)
        self.outer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.outer_splitter.addWidget(self.ai_chat_panel)
        self.outer_splitter.addWidget(splitter)
        self.outer_splitter.setCollapsible(0, False)
        self.outer_splitter.setStretchFactor(0, 0)
        self.outer_splitter.setStretchFactor(1, 1)
        self.outer_splitter.setSizes([0, 1280])
        self.setCentralWidget(self.outer_splitter)
    
    def _setup_menubar(self):
        """菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        open_dir_action = QAction("添加素材文件夹(&O)...", self)
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
        
        trans_all_action = QAction("识别全部未完成音频(&A)", self)
        trans_all_action.setShortcut("Ctrl+Shift+A")
        trans_all_action.triggered.connect(self._on_transcribe_all)
        trans_menu.addAction(trans_all_action)
        
        trans_selected_action = QAction("识别选中音频(&S)", self)
        trans_selected_action.setShortcut("Ctrl+T")
        trans_selected_action.triggered.connect(self._on_transcribe_selected)
        trans_menu.addAction(trans_selected_action)
        
        # 同步菜单
        sync_menu = menubar.addMenu("同步(&Y)")
        
        sync_goto_action = QAction("打开同步面板(&S)", self)
        sync_goto_action.setShortcut("Ctrl+D")
        sync_goto_action.triggered.connect(
            lambda: self.right_tabs.setCurrentWidget(self.sync_panel)
        )
        sync_menu.addAction(sync_goto_action)
        
        # 设置菜单
        settings_menu = menubar.addMenu("设置(&S)")

        recognition_settings_action = QAction("语音识别", self)
        recognition_settings_action.setShortcut("Ctrl+,")
        recognition_settings_action.triggered.connect(
            lambda: self._on_settings("recognition")
        )
        settings_menu.addAction(recognition_settings_action)
        lyrics_settings_action = QAction("歌词输出", self)
        lyrics_settings_action.triggered.connect(lambda: self._on_settings("lyrics"))
        settings_menu.addAction(lyrics_settings_action)
        shortcut_settings_action = QAction("快捷键", self)
        shortcut_settings_action.triggered.connect(lambda: self._on_settings("shortcuts"))
        settings_menu.addAction(shortcut_settings_action)
        cache_settings_action = QAction("缓存", self)
        cache_settings_action.triggered.connect(lambda: self._on_settings("cache"))
        settings_menu.addAction(cache_settings_action)
        local_ai_settings_action = QAction("本地部署 AI", self)
        local_ai_settings_action.triggered.connect(lambda: self._on_settings("local_ai"))
        settings_menu.addAction(local_ai_settings_action)

        key_action = QAction("密钥管理(&K)...", self)
        key_action.triggered.connect(self._on_key_manager)
        menubar.addAction(key_action)

        self.ai_mode_action = QAction("AI 模式", self)
        self.ai_mode_action.triggered.connect(self._show_ai_mode_menu)
        menubar.addAction(self.ai_mode_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        guide_action = QAction("使用与接口说明(&G)", self)
        guide_action.setShortcut("F1")
        guide_action.triggered.connect(self._on_help_guide)
        help_menu.addAction(guide_action)

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

        self.resource_label = QLabel("")
        self.resource_label.setStyleSheet("color:#5B6573;padding-left:10px")
        self.resource_label.setVisible(False)
        self.statusbar.addPermanentWidget(self.resource_label)
        self.resource_timer = QTimer(self)
        self.resource_timer.setInterval(1000)
        self.resource_timer.timeout.connect(self._refresh_resource_usage)
        
        self._refresh_statusbar()
    
    def _refresh_statusbar(self):
        """刷新状态栏信息"""
        songs = self.song_list_panel.get_all_songs()
        has_lrc = sum(1 for s in songs if s.get("has_lrc"))
        total = len(songs)
        if self.library_panel.mode == "video":
            self.count_label.setText(f"共 {total} 个视频素材")
        else:
            self.count_label.setText(f"共 {total} 个音频素材 | 已完成 {has_lrc} 个")
        
        provider = self.router.get(self.config.asr.provider)
        if provider and provider.is_available():
            self.provider_label.setText(f"引擎: {provider.display_name}")
        elif self.config.asr.provider == "xunfei":
            self.provider_label.setText("引擎: 讯飞（请补齐三项密钥）")
        else:
            self.provider_label.setText("引擎: 不可用 (请检查设置)")
        if hasattr(self, "batch_operations_panel"):
            self.batch_operations_panel.update_scope(songs)
    
    def _connect_signals(self):
        """连接信号"""
        # 文件夹树 → 歌曲列表
        self.library_panel.folder_selected.connect(self._on_folder_selected)
        self.library_panel.material_selected.connect(self._on_material_selected)
        self.library_panel.mode_changed.connect(self._on_material_mode_changed)
        self.library_panel.select_all_changed.connect(self._on_material_select_all_changed)
        self.library_panel.directories_changed.connect(self._on_material_directories_changed)
        self.library_panel.calibration_changed.connect(self._on_video_calibration_changed)
        self.library_panel.aggregate_requested.connect(self._on_video_aggregate)
        self.library_panel.export_requested.connect(self._on_video_export)
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)
        
        # 歌曲列表 → 详情面板
        self.song_list_panel.song_selected.connect(self.detail_panel.show_song)
        self.song_list_panel.song_selected.connect(self.lyrics_preview_panel.show_song)
        self.song_list_panel.song_selected.connect(self.online_lyrics_panel.show_song)
        self.lyrics_preview_panel.lyrics_saved.connect(self._on_preview_lyrics_saved)
        self.ai_chat_panel.command_requested.connect(self._on_ai_command_requested)
        
        # 详情面板 → 请求识别
        self.detail_panel.transcribe_clicked.connect(self._on_transcribe_single)
        self.detail_panel.edit_lyrics_clicked.connect(self._on_edit_lyrics)
        self.detail_panel.translate_requested.connect(self._on_translate_lyrics)
        self.online_lyrics_panel.action_requested.connect(self._on_online_lyrics_action)
        self.batch_operations_panel.batch_transcribe_requested.connect(
            self._on_transcribe_all
        )
        self.batch_operations_panel.batch_translate_requested.connect(
            self._on_batch_translate_lyrics
        )
        self.batch_operations_panel.batch_online_requested.connect(
            self._on_batch_online_lyrics
        )
        
        # 刷新计数
        self.song_list_panel.model_updated.connect(self._refresh_statusbar)
        
        self._refresh_statusbar()
    # ─── 事件处理 ─────────────────────────────

    def _on_open_folder(self):
        """向当前素材模式添加文件夹"""
        self.library_panel.open_directory_picker()
    
    def _on_folder_selected(self, folder_path: str):
        """文件夹被选中 → 扫描当前模式的素材"""
        self._selected_material_folder = folder_path
        if not folder_path:
            self.song_list_panel.load_songs([], root_dir="")
            self.library_panel.clear_video_materials()
            self._refresh_statusbar()
            self.status_label.setText("已取消添加素材文件夹")
            return
        self.status_label.setText(f"扫描中: {folder_path}...")
        directories = (
            self.config.video_dirs if self.library_panel.mode == "video" else self.config.music_dirs
        )
        scan_directories = directories if self.library_panel.select_all else [folder_path]
        if self.library_panel.mode == "video":
            offset = self.config.video_time_offsets.get(str(Path(folder_path).resolve()), 0)
            materials = []
            selected_materials = []
            for directory in scan_directories:
                directory_offset = self.config.video_time_offsets.get(
                    str(Path(directory).resolve()), 0
                )
                scanned = scan_videos(directory, offset_seconds=directory_offset)
                materials.extend(scanned)
                if directory == folder_path:
                    selected_materials = scanned
            self.library_panel.set_video_materials(folder_path, selected_materials, offset)
        else:
            materials = []
            for directory in scan_directories:
                materials.extend(scan_audio(directory))
            self.library_panel.clear_video_materials()
        self.song_list_panel.load_songs(
            materials, root_dir="" if self.library_panel.select_all else folder_path
        )
        self._refresh_statusbar()

        if self.library_panel.mode == "music":
            self.sync_panel.set_dir_a(folder_path)

        self.status_label.setText("就绪")

    def _start_resource_monitor(self):
        """Show live machine usage only while the local ASR engine is working."""
        self._refresh_resource_usage()
        self.resource_label.setVisible(True)
        self.resource_timer.start()

    def _stop_resource_monitor(self):
        self.resource_timer.stop()
        self.resource_label.clear()
        self.resource_label.setVisible(False)

    def _refresh_resource_usage(self):
        self.resource_label.setText(format_resource_usage(sample_resource_usage()))

    def _on_material_mode_changed(self, mode: str):
        self.song_list_panel.set_material_mode(mode)
        self._refresh_statusbar()

    def _on_material_select_all_changed(self, mode: str, selected: bool):
        if mode == "video":
            self.config.video_select_all = selected
            directories = self.config.video_dirs
        else:
            self.config.music_select_all = selected
            directories = self.config.music_dirs
        config_manager.save()
        folder = self._selected_material_folder
        if folder not in directories:
            folder = directories[0] if directories else ""
        if folder:
            self._on_folder_selected(folder)

    def _on_material_selected(self, material_path: str):
        """Show the selected audio or video material's same-name LRC on the left."""
        path = Path(material_path)
        lrc_path = path.with_suffix(".lrc")
        song = {
            "name": path.name,
            "path": str(path),
            "lrc_path": str(lrc_path),
            "has_lrc": lrc_path.is_file(),
        }
        self.lyrics_preview_panel.show_song(song)
        self.online_lyrics_panel.show_song(song)
        self.left_stack.setCurrentWidget(self.lyrics_preview_panel)

    def _on_online_lyrics_action(self, media_path: str, match, action: str):
        lrc_path = Path(media_path).with_suffix(".lrc")
        if action == "apply":
            reply = QMessageBox.question(
                self,
                "下载同步歌词",
                f"将把 LRCLIB 的同步歌词写入：\n{lrc_path}\n\n"
                "已有 LRC 会先备份；音频文件不会修改。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            from core.online_lyrics import apply_synced_lyrics

            try:
                output, backup = apply_synced_lyrics(lrc_path, match)
            except (OSError, RuntimeError) as exc:
                QMessageBox.warning(self, "下载同步歌词", str(exc))
                return
            self._refresh_after_online_lyrics_write(media_path, str(output))
            backup_message = f"\n备份：{backup}" if backup else ""
            QMessageBox.information(
                self, "下载同步歌词", f"同步歌词已写入：{output}{backup_message}"
            )
            return

        if not lrc_path.is_file():
            QMessageBox.information(self, "AI 校准", "请先识别或下载一份本地 LRC。")
            return
        from core.ai_assistant import settings_from_config

        ai_settings = settings_from_config(self.config)
        if ai_settings.requires_api_key and not ai_settings.api_key:
            QMessageBox.information(self, "AI 校准", "请先配置当前在线 AI 的 API Key。")
            return
        if not ai_settings.base_url.strip() or not ai_settings.model.strip():
            QMessageBox.information(self, "AI 校准", "请先配置 AI 接口地址和模型名称。")
            return
        reply = QMessageBox.question(
            self,
            "AI 核对并校准",
            "AI 将参考所选公开歌词修正本地歌词文字。\n"
            "本地时间戳和音频保持不变，原 LRC 会先备份。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.online_lyrics_panel.status_label.setText("AI 正在核对并校准歌词…")
        self.online_calibration_worker = LyricsCalibrationWorker(
            str(lrc_path), match, ai_settings, self
        )
        self.online_calibration_worker.completed.connect(
            lambda output, backup: self._on_online_calibration_finished(
                media_path, output, backup
            )
        )
        self.online_calibration_worker.failed.connect(self._on_online_calibration_failed)
        self.online_calibration_worker.start()

    def _on_online_calibration_finished(
        self, media_path: str, output_path: str, backup_path: str
    ):
        self._refresh_after_online_lyrics_write(media_path, output_path)
        QMessageBox.information(
            self,
            "AI 校准完成",
            f"已保留本地时间轴并更新歌词文字。\n备份：{backup_path}",
        )

    def _on_online_calibration_failed(self, message: str):
        self.online_lyrics_panel.status_label.setText(f"AI 校准失败：{message}")
        QMessageBox.warning(self, "AI 校准失败", message)

    def _refresh_after_online_lyrics_write(self, media_path: str, lrc_path: str):
        self.song_list_panel.update_song_status(media_path, True)
        song = dict(self.online_lyrics_panel._song)
        song.update({"has_lrc": True, "lrc_path": lrc_path})
        self.detail_panel.show_song(song)
        self.lyrics_preview_panel.show_song(song)
        self.online_lyrics_panel._song = song
        self.online_lyrics_panel.refresh_local_comparison()
        self.online_lyrics_panel.status_label.setText("本地歌词已更新，音频文件未修改。")
        self._refresh_statusbar()

    def _on_preview_lyrics_saved(self, lrc_path: str):
        """Refresh completion state after an inline material-library lyric edit."""
        for song in self.song_list_panel.get_all_songs():
            if Path(song["path"]).with_suffix(".lrc") == Path(lrc_path):
                self.song_list_panel.update_song_status(song["path"], True)
                break
        self.status_label.setText("歌词已保存")
        self._refresh_statusbar()

    def _on_right_tab_changed(self, index: int):
        self.left_stack.setCurrentWidget(
            self.lyrics_preview_panel if self.right_tabs.widget(index) is self.library_panel else self.song_list_panel
        )

    def _on_material_directories_changed(self, mode: str, directories: list[str]):
        if mode == "video":
            removed = set(self.config.video_dirs) - set(directories)
            self.config.video_dirs = directories
            for folder_path in removed:
                self.config.video_time_offsets.pop(str(Path(folder_path).resolve()), None)
        else:
            self.config.music_dirs = directories
        config_manager.save()

    def _on_video_calibration_changed(self, folder_path: str, source, target):
        key = str(Path(folder_path).resolve())
        if target is None:
            self.config.video_time_offsets.pop(key, None)
            offset = 0
        else:
            offset = int((target - source).total_seconds())
            self.config.video_time_offsets[key] = offset
        config_manager.save()
        write_video_transcript_timeline(folder_path, offset)
        self._on_folder_selected(folder_path)

    def _on_video_aggregate(self, folder_path: str):
        reply = QMessageBox.question(
            self,
            "按时间汇总视频",
            "将按校准后的时间排序，并在当前文件夹创建新的“视频汇总_时间”子目录。\n"
            "原始视频不会被修改，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from ui.video_aggregate_worker import VideoAggregateWorker

        offset = self.config.video_time_offsets.get(str(Path(folder_path).resolve()), 0)
        self.video_aggregate_worker = VideoAggregateWorker(folder_path, offset, self)
        self.video_aggregate_worker.finished.connect(self._on_video_aggregate_finished)
        self.status_label.setText("正在按时间汇总视频，请稍候...")
        self.video_aggregate_worker.start()

    def _on_video_aggregate_finished(self, success: bool, result: object):
        if not success:
            self.status_label.setText("视频汇总失败")
            QMessageBox.warning(self, "视频汇总失败", str(result))
            return
        self.status_label.setText("视频汇总完成")
        QMessageBox.information(
            self,
            "视频汇总完成",
            f"已汇总 {result.video_count} 个视频。\n输出目录：{result.output_dir}",
        )

    def _on_video_export(self, folder_path: str):
        offset = self.config.video_time_offsets.get(str(Path(folder_path).resolve()), 0)
        output_path, row_count = write_video_transcript_timeline(folder_path, offset)
        QMessageBox.information(
            self,
            "导出完成",
            f"已导出 {row_count} 条文字时间记录。\n输出文件：{output_path}",
        )
    
    def _on_transcribe_single(self, file_path: str):
        """识别单首歌"""
        self._run_transcription([file_path])

    def _on_translate_lyrics(
        self, lrc_path: str, engine: str, source_language: str, target_language: str
    ):
        self._run_translation([lrc_path], engine, source_language, target_language)

    def _on_batch_translate_lyrics(
        self, engine: str, source_language: str, target_language: str
    ):
        lrc_paths = [
            str(Path(song["path"]).with_suffix(".lrc"))
            for song in self.song_list_panel.get_all_songs()
            if song.get("has_lrc")
        ]
        if not lrc_paths:
            QMessageBox.information(self, "批量翻译", "当前列表没有可翻译的 LRC 歌词。")
            return
        reply = QMessageBox.question(
            self,
            "批量翻译",
            f"将翻译当前列表中的 {len(lrc_paths)} 份歌词，并生成独立译文文件。\n"
            "原 LRC 不会被覆盖，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_translation(lrc_paths, engine, source_language, target_language)

    def _on_batch_online_lyrics(self, apply_best: bool, minimum_score: float):
        songs = [
            song
            for song in self.song_list_panel.get_all_songs()
            if not song.get("instrumental")
        ]
        if not songs:
            QMessageBox.information(
                self, "批量在线匹配", "当前列表没有可在线匹配的素材。"
            )
            return
        if apply_best:
            reply = QMessageBox.question(
                self,
                "批量在线匹配",
                f"将搜索 {len(songs)} 个素材，并自动写入匹配分不低于 "
                f"{minimum_score:.0f}% 的最佳同步歌词。\n"
                "已有 LRC 会先备份，媒体文件不会修改。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.batch_operations_panel.begin_online_task(len(songs))
        self.batch_online_worker = BatchOnlineLyricsWorker(
            songs,
            apply_best=apply_best,
            minimum_score=minimum_score,
            parent=self,
        )
        self.batch_online_worker.progress.connect(
            self.batch_operations_panel.show_online_progress
        )
        self.batch_online_worker.completed.connect(
            self._on_batch_online_lyrics_finished
        )
        self.batch_online_worker.start()

    def _on_batch_online_lyrics_finished(self, results: list[dict]):
        self.batch_operations_panel.finish_online_task(results)
        applied = [item for item in results if item["status"] == "applied"]
        matched = [item for item in results if item["status"] == "matched"]
        failed = [item for item in results if item["status"] == "failed"]
        for item in applied:
            self.song_list_panel.update_song_status(item["path"], True)
        self._refresh_statusbar()
        self.status_label.setText(
            f"批量在线匹配完成：匹配 {len(matched) + len(applied)}，"
            f"写入 {len(applied)}，失败 {len(failed)}"
        )
        if applied:
            selected = self.song_list_panel.get_selected_songs()
            if selected:
                self.online_lyrics_panel.show_song(selected[0])

    def _run_translation(
        self,
        lrc_paths: list[str],
        engine: str,
        source_language: str,
        target_language: str,
    ):
        if source_language == target_language:
            QMessageBox.information(self, "歌词翻译", "源语言和目标语言不能相同。")
            return
        self.config.translation_engine = engine
        self.config.translation_source_language = source_language
        self.config.translation_target_language = target_language
        config_manager.save()
        from ui.translation_worker import TranslationWorker

        self.translation_worker = TranslationWorker(
            lrc_paths,
            engine=engine,
            source_language=source_language,
            target_language=target_language,
            config=self.config,
            parent=self,
        )
        self.translation_worker.progress.connect(
            lambda current, total, name: self.status_label.setText(
                f"翻译中 {current}/{total}：{name}"
            )
        )
        self.translation_worker.finished.connect(self._on_translation_finished)
        self.translation_worker.start()

    def _on_translation_finished(self, results: dict):
        successes = [
            (source, result["output"])
            for source, result in results.items()
            if result.get("success")
        ]
        failures = [
            str(result.get("error", "未知错误"))
            for result in results.values()
            if not result.get("success")
        ]
        for source_path, translated_path in successes:
            self.detail_panel.translation_completed(source_path, translated_path)
        self.status_label.setText(
            f"翻译完成：成功 {len(successes)}，失败 {len(failures)}"
        )
        if failures:
            unique_errors = list(dict.fromkeys(failures))
            QMessageBox.warning(
                self,
                "歌词翻译",
                f"成功 {len(successes)} 份，失败 {len(failures)} 份。\n\n"
                + "\n".join(unique_errors[:3]),
            )
    
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
        """识别全部未完成素材"""
        songs = self.song_list_panel.get_all_songs()
        files = [s["path"] for s in songs if not s.get("has_lrc") and not s.get("instrumental")]
        if not files:
            QMessageBox.information(self, "提示", "当前素材均已完成识别！")
            return
        
        reply = QMessageBox.question(
            self, "确认", f"将为 {len(files)} 个素材识别音轨，是否继续？",
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
            elif provider_name == "xunfei":
                msg = (
                    "讯飞极速录音转写不可用。\n\n"
                    "请在“密钥管理”中填写同一讯飞应用的 AppID、API Key、API Secret，"
                    "并确认已开通极速录音转写服务。"
                )
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
        self.trans_progress.setRange(0, 0)
        self.trans_progress.setFormat("正在识别，请耐心等待")
        self.total_trans_progress.setVisible(len(files) > 1)
        self.total_trans_progress.setRange(0, len(files))
        self.total_trans_progress.setFormat("总进度 %v/%m")
        self.total_trans_progress.setValue(0)
        self._transcription_total = len(files)
        self._batch_completed = 0
        self.status_label.setText(f"识别中... 0/{len(files)}")
        if provider_name == "local":
            self._start_resource_monitor()
        else:
            self._stop_resource_monitor()
        self.worker.start()
    
    def _on_transcribe_progress(self, current: int, total: int, filename: str):
        if total > 1:
            self.total_trans_progress.setValue(current - 1)
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
        self.status_label.setText(message)
    
    def _on_stage_progress(self, msg: str):
        self.status_label.setText(msg)
    
    def _on_stop_transcribe(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.requestInterruption()
            self.btn_stop_transcribe.setEnabled(False)
            self.status_label.setText("正在停止...")
    
    def _on_song_done(self, file_path: str, lrc_path: str, success: bool):
        self._batch_completed += 1
        if self._transcription_total > 1:
            self.total_trans_progress.setValue(self._batch_completed)
        self.song_list_panel.update_song_status(file_path, success)
        # 识别成功后立即刷新右侧详情面板
        if success:
            songs = self.song_list_panel.get_all_songs()
            for s in songs:
                if s["path"] == file_path:
                    self.detail_panel.show_song(s)
                    break
        # 自动检测纯音乐：歌词太短（<20字）可能是纯音乐
        if self.library_panel.mode == "music" and success and lrc_path and os.path.exists(lrc_path):
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
        self._stop_resource_monitor()
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
                if "无法连接 Groq 服务" in err_detail:
                    hint = "当前为网络连接问题；请检查代理、DNS 或防火墙。"
                elif "API Key" in err_detail or "鉴权" in err_detail:
                    hint = "请检查 Groq API Key 配置。"
                else:
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
    
    def _on_settings(self, section: str = "recognition"):
        """从顶栏设置菜单打开指定分类的设置对话框。"""
        dialog = SettingsDialog(self.config, self, section=section)
        result = dialog.exec()
        if result == 42:
            # GPU 安装完成，重启应用
            import logging
            logging.getLogger("linlangyuefu").info("GPU 安装完成，准备重启...")
            self._do_restart()
        elif result:
            # 设置已保存，重建 router
            self.router = get_router(self.config)
            self._configure_voice_input_shortcut()
            self.detail_panel.reload_translation_settings()
            self.batch_operations_panel.reload_translation_settings()
            self._refresh_statusbar()

    def _on_key_manager(self):
        """Open the local credential manager and rebuild the ASR router if saved."""
        dialog = KeyManagerDialog(self.config, self)
        dialog.asr_provider_saved.connect(self._on_asr_provider_saved)
        if dialog.exec():
            self.router = get_router(self.config)
            self._refresh_statusbar()

    def _on_asr_provider_saved(self, provider: str):
        self.config.asr.provider = provider

    def _on_ai_command_requested(self, raw_command: str):
        try:
            command = validate_cli_command(raw_command)
        except ValueError as exc:
            self.ai_chat_panel.append_command_result(f"已拒绝命令：{exc}")
            return
        if command.needs_confirmation:
            reply = QMessageBox.question(
                self,
                "确认 AI 操作",
                f"AI 请求执行：\n{raw_command}\n\n该操作会修改软件配置、文件或缓存，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.ai_chat_panel.append_command_result("已取消需要确认的 AI 操作。")
                return
        self.ai_chat_panel.append_command_result(f"正在执行：{raw_command}")
        self._ai_command_worker = CLICommandWorker(command, self)
        self._ai_command_worker.completed.connect(
            lambda output: self._on_ai_command_finished(raw_command, True, output)
        )
        self._ai_command_worker.failed.connect(
            lambda error: self._on_ai_command_finished(raw_command, False, error)
        )
        self._ai_command_worker.start()

    def _on_ai_command_finished(self, raw_command: str, success: bool, output: str):
        self.ai_chat_panel.append_command_result(
            f"{'完成' if success else '失败'}：{raw_command}\n{output}"
        )
        if success:
            self.config = config_manager.load()
            self.router = get_router(self.config)
            self._configure_voice_input_shortcut()
            self._refresh_statusbar()

    def _show_ai_mode_menu(self):
        menu = QMenu(self)
        toggle = menu.addAction("关闭" if self._ai_mode_enabled else "启动")
        toggle.triggered.connect(self._toggle_ai_mode)
        rect = self.menuBar().actionGeometry(self.ai_mode_action)
        menu.exec(self.menuBar().mapToGlobal(rect.bottomLeft()))

    def _toggle_ai_mode(self):
        if self._ai_mode_enabled:
            self.ai_chat_panel.setVisible(False)
            self.outer_splitter.setSizes([0, max(1, self.width())])
            self._ai_mode_enabled = False
            return
        from core.ai_assistant import settings_from_config

        ai_settings = settings_from_config(self.config)
        if ai_settings.requires_api_key and not ai_settings.api_key:
            QMessageBox.information(
                self,
                "AI 模式",
                "请先在“密钥管理”中填写在线 AI 的 API Key，然后再启动 AI 模式。",
            )
            return
        if not ai_settings.base_url.strip() or not ai_settings.model.strip():
            QMessageBox.information(
                self,
                "AI 模式",
                "请先在“设置 → 本地部署 AI”中填写接口地址和模型名称。",
            )
            return
        self.ai_chat_panel.setVisible(True)
        self.outer_splitter.setSizes(
            [self._ai_panel_width, max(1, self.width() - self._ai_panel_width)]
        )
        self._ai_mode_enabled = True

    def _configure_voice_input_shortcut(self):
        self._voice_shortcut.setKey(QKeySequence(self.config.voice_input_shortcut))

    def _toggle_voice_input_shortcut(self):
        if not self._ai_mode_enabled:
            self.status_label.setText("请先启动 AI 模式，再使用语音输入快捷键。")
            return
        self.ai_chat_panel.toggle_voice_input()
    
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
            "<p>版本: 0.4.0-dev</p>"
            "<hr>"
            "<p>技术栈: Python + PyQt6 + Whisper</p>"
            "<p>ASR: Groq Whisper / OpenAI Whisper</p>"
        )

    def _on_help_guide(self):
        """Show offline documentation bundled into the desktop UI."""
        self.help_dialog = HelpDialog(self)
        self.help_dialog.exec()
