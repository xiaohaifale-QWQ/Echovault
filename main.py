"""
MusicSync — 音乐歌词识别同步系统

用法:
    python main.py                  # 启动图形界面（默认）
    python main.py gui              # 启动图形界面
    python main.py transcribe <文件> # 命令行识别
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import config_manager
from core.asr.router import ASRRouter, get_router
from core.audio_utils import is_supported, SUPPORTED_FORMATS
from core.lrc_writer import transcribe_and_save_lrc

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("musicsync")


def cmd_transcribe(args):
    """命令行：转录音频"""
    target = Path(args.target)
    
    if not target.exists():
        logger.error(f"文件/文件夹不存在: {target}")
        sys.exit(1)
    
    # 收集待处理的音频文件
    audio_files = []
    if target.is_file():
        if is_supported(str(target)):
            audio_files.append(str(target))
        else:
            logger.error(f"不支持的音频格式: {target.suffix}")
            sys.exit(1)
    elif target.is_dir():
        for ext in SUPPORTED_FORMATS:
            audio_files.extend(str(p) for p in target.rglob(f"*{ext}"))
        if not audio_files:
            logger.error(f"文件夹中没有支持的音频文件")
            sys.exit(1)
    else:
        logger.error(f"无效路径: {target}")
        sys.exit(1)
    
    logger.info(f"找到 {len(audio_files)} 个音频文件")
    
    # 加载配置
    config = config_manager.load()
    
    # 初始化 ASR 路由器
    router = get_router(config)
    available = router.list_available()
    
    if not available:
        logger.error(
            "没有可用的 ASR Provider。\n"
            "请设置 GROQ_API_KEY 环境变量，或安装本地 Whisper。\n"
            "免费获取 Groq API Key: https://console.groq.com/keys"
        )
        sys.exit(1)
    
    logger.info(f"可用 Provider: {[p.display_name for p in available]}")
    
    # 逐个处理
    success = 0
    failed = 0
    skipped = 0
    
    for i, audio_path in enumerate(audio_files, 1):
        name = Path(audio_path).name
        lrc_path = str(Path(audio_path).with_suffix(".lrc"))
        
        # 跳过已有 LRC 的文件
        if os.path.exists(lrc_path) and not args.force:
            logger.info(f"[{i}/{len(audio_files)}] ⏭ 跳过（已有LRC）: {name}")
            skipped += 1
            continue
        
        try:
            logger.info(f"[{i}/{len(audio_files)}] 识别中: {name}")
            
            lrc_path = transcribe_and_save_lrc(
                audio_path=audio_path,
                router=router,
                language=args.language,
                output_dir=args.output_dir,
                overwrite=args.force,
            )
            
            logger.info(f"[{i}/{len(audio_files)}] 完成: {name} -> {Path(lrc_path).name}")
            success += 1
            
        except FileExistsError:
            logger.info(f"[{i}/{len(audio_files)}] ⏭ 跳过: {name} (LRC已存在)")
            skipped += 1
        except Exception as e:
            logger.error(f"[{i}/{len(audio_files)}] 失败: {name} - {e}")
            failed += 1
    
    # 汇总
    logger.info("=" * 40)
    logger.info(f"处理完成: 成功 {success} | 跳过 {skipped} | 失败 {failed}")


def cmd_gui(args):
    """启动图形界面"""
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    
    app = QApplication(sys.argv)
    app.setApplicationName("MusicSync")
    app.setOrganizationName("MusicSync")
    
    # 样式
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


def main():
    parser = argparse.ArgumentParser(
        prog="musicsync",
        description="MusicSync — AI 歌词识别 + 文件同步",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py transcribe E:/music/song.mp3
  python main.py transcribe E:/music/ --language zh
  python main.py transcribe E:/music/ --force --output-dir ./lyrics
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # transcribe 命令
    trans_parser = subparsers.add_parser("transcribe", help="识别歌曲歌词")
    trans_parser.add_argument("target", help="音频文件或文件夹路径")
    trans_parser.add_argument("--language", "-l", help="语言代码 (zh/en/ja/ko)")
    trans_parser.add_argument("--force", "-f", action="store_true", help="强制覆盖已有 LRC")
    trans_parser.add_argument("--output-dir", "-o", help="LRC 输出目录（默认与音频同目录）")
    trans_parser.add_argument("--provider", "-p", help="指定 ASR Provider")
    trans_parser.set_defaults(func=cmd_transcribe)
    
    # gui 命令
    gui_parser = subparsers.add_parser("gui", help="启动图形界面")
    gui_parser.set_defaults(func=cmd_gui)
    
    args = parser.parse_args()
    
    # 如果没有子命令，默认启动 GUI
    if args.command is None:
        cmd_gui(args)
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
