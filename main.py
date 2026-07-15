"""
琳琅乐府 - 音乐歌词识别同步系统

用法:
    python main.py                       # 启动图形界面
    python main.py gui                   # 启动图形界面
    python main.py <命令> [参数]          # CLI 模式

CLI 命令: list | info | transcribe | lyrics | config | model | gpu | sync | rename | mark | serve | doctor
详细文档: CLI.md
"""

import sys
import os
import json as _json
import argparse
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLI_OUTPUT_PATH_ENV = "ECHOVAULT_CLI_OUTPUT_PATH"

def _configure_utf8_stream(stream):
    """Return a writable UTF-8 stream, including in windowed executables."""
    if stream is None:
        output_path = os.environ.get(CLI_OUTPUT_PATH_ENV, "").strip()
        if output_path:
            return open(output_path, "a", encoding="utf-8", newline="\n")
        return open(os.devnull, "w", encoding="utf-8")
    if getattr(stream, "encoding", None) == "utf-8":
        return stream
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
    return stream


# Force UTF-8 console output while remaining compatible with PyInstaller's
# windowed mode, where sys.stdout and sys.stderr are both None. Whisper/tqdm still
# writes progress output in GUI mode, so a writable null stream is required.
sys.stdout = _configure_utf8_stream(sys.stdout)
sys.stderr = _configure_utf8_stream(sys.stderr)

from core.config import config_manager, AppConfig, update_config_value
from core.asr.router import ASRRouter, get_router
from core.audio_utils import is_supported, SUPPORTED_FORMATS
from core.lrc_writer import transcribe_and_save_lrc
from core.lrc_parser import parse_lrc_file
from core.environment import build_environment_report
from core.voice_cache import clear_voice_cache, voice_cache_dir
from services.library_service import InstrumentalStore, scan_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("linlangyuefu")


# ============================================================
# Utilities
# ============================================================

def _scan_audio(folder):
    return scan_audio(folder)


def _fmt_size(b):
    if b >= 1_073_741_824: return f"{b/1_073_741_824:.1f} GB"
    if b >= 1_048_576: return f"{b/1_048_576:.1f} MB"
    if b >= 1_024: return f"{b/1_024:.0f} KB"
    return f"{b} B"


def _out(data, args):
    if getattr(args, "json_output", False):
        print(_json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, list):
        for item in data: print(item)
    elif isinstance(data, dict):
        for k, v in data.items(): print(f"{k}: {v}")
    else:
        print(data)


# ============================================================
# list - list songs
# ============================================================

def cmd_list(args):
    config = config_manager.load()
    folder = args.folder or (config.music_dirs[0] if config.music_dirs else None)
    if not folder:
        logger.error("Please specify folder path")
        sys.exit(1)
    if not Path(folder).exists():
        logger.error(f"Folder not found: {folder}")
        sys.exit(1)

    songs = _scan_audio(folder)
    if args.status == "has-lrc":
        songs = [s for s in songs if s["has_lrc"]]
    elif args.status == "no-lrc":
        songs = [s for s in songs if not s["has_lrc"]]
    elif args.status == "instrumental":
        songs = [s for s in songs if s.get("instrumental")]
    if args.format:
        fmt = "." + args.format.lower()
        songs = [s for s in songs if Path(s["name"]).suffix.lower() == fmt]
    if args.search:
        kw = args.search.lower()
        songs = [s for s in songs if kw in Path(s["name"]).stem.lower()]

    if args.json_output:
        out = []
        for s in songs:
            out.append({"name": s["name"], "path": s["path"], "size": s["size"],
                        "size_human": _fmt_size(s["size"]), "has_lrc": s["has_lrc"],
                        "folder": s["folder"]})
        print(_json.dumps(out, ensure_ascii=False, indent=2))
    else:
        has = sum(1 for s in songs if s["has_lrc"])
        print(f"Folder: {folder}")
        print(f"Total: {len(songs)} (has lyrics: {has}, no lyrics: {len(songs)-has})")
        print("-" * 60)
        for s in songs:
            st = "Y" if s["has_lrc"] else "N"
            print(f"  [{st}] {s['name']:<40s} {_fmt_size(s['size']):>8s}  {s['folder']}")


# ============================================================
# info - song detail
# ============================================================

def cmd_info(args):
    fp = args.file
    if not Path(fp).exists():
        logger.error(f"File not found: {fp}")
        sys.exit(1)

    pf = Path(fp)
    lrc_path = str(pf.with_suffix(".lrc"))
    has_lrc = os.path.exists(lrc_path)
    info = {
        "name": pf.name, "path": str(pf),
        "size": pf.stat().st_size, "size_human": _fmt_size(pf.stat().st_size),
        "format": pf.suffix.upper().lstrip("."),
        "has_lrc": has_lrc, "lrc_path": lrc_path if has_lrc else None,
    }
    try:
        from core.metadata import read_tags
        meta = read_tags(str(pf))
        if meta.get("title"): info["title"] = meta["title"]
        if meta.get("artist"): info["artist"] = meta["artist"]
        if meta.get("album"): info["album"] = meta["album"]
    except Exception:
        pass

    if args.json_output:
        print(_json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"File: {info['name']}")
        print(f"Path: {info['path']}")
        print(f"Size: {info['size_human']}")
        print(f"Format: {info['format']}")
        if info.get("title"): print(f"Title: {info['title']}")
        if info.get("artist"): print(f"Artist: {info['artist']}")
        if info.get("album"): print(f"Album: {info['album']}")
        print(f"Lyrics: {'YES' if has_lrc else 'NO'}")
        if has_lrc:
            lrc = parse_lrc_file(lrc_path)
            print(f"Lines: {len(lrc.lines)}")


# ============================================================
# transcribe
# ============================================================

def cmd_transcribe(args):
    target = Path(args.target)
    if not target.exists():
        logger.error(f"Target not found: {target}")
        sys.exit(1)

    files = []
    if target.is_file():
        if is_supported(str(target)):
            files.append(str(target))
        else:
            logger.error(f"Unsupported format: {target.suffix}")
            sys.exit(1)
    elif target.is_dir():
        files.extend(song["path"] for song in scan_audio(target) if not song["instrumental"])
        if not files:
            logger.error("No supported audio files found")
            sys.exit(1)

    if not args.quiet:
        logger.info(f"Found {len(files)} audio files")

    config = config_manager.load()
    router = get_router(config)
    provider = router.get(args.provider or config.asr.provider)
    if not provider or not provider.is_available():
        logger.error(f"Provider not available: {args.provider or config.asr.provider}")
        sys.exit(1)
    if not args.quiet:
        logger.info(f"Engine: {provider.display_name}")

    results = []
    ok = fail = skip = 0
    for i, fp in enumerate(files, 1):
        name = Path(fp).name
        lrc_p = str(Path(fp).with_suffix(".lrc"))
        if os.path.exists(lrc_p) and not args.force:
            if not args.quiet: logger.info(f"[{i}/{len(files)}] SKIP {name}")
            skip += 1; results.append({"file": name, "status": "skipped"})
            continue
        try:
            if not args.quiet: logger.info(f"[{i}/{len(files)}] TRANS {name}")
            out = transcribe_and_save_lrc(
                audio_path=fp, router=router,
                language=args.language, output_dir=args.output_dir,
                overwrite=args.force,
            )
            if not args.quiet: logger.info(f"[{i}/{len(files)}] OK   {name}")
            ok += 1; results.append({"file": name, "status": "ok", "lrc_path": out})
        except FileExistsError:
            skip += 1; results.append({"file": name, "status": "skipped"})
        except Exception as e:
            if not args.quiet: logger.error(f"[{i}/{len(files)}] FAIL {name}: {e}")
            fail += 1; results.append({"file": name, "status": "failed", "error": str(e)})

    summary = {"total": len(files), "ok": ok, "failed": fail, "skipped": skip}
    if args.json_output:
        print(_json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"\nDone: ok={ok} skip={skip} fail={fail}")
    if fail > 0:
        sys.exit(1)


# ============================================================
# lyrics
# ============================================================

def cmd_lyrics(args):
    if args.lyrics_action == "show":
        fp = args.file
        lrc_p = str(Path(fp).with_suffix(".lrc"))
        if not os.path.exists(lrc_p):
            logger.error(f"LRC not found: {lrc_p}")
            sys.exit(1)
        lrc = parse_lrc_file(lrc_p)
        if args.json_output:
            lines = [{"ts": ln.timestamp, "text": ln.text} for ln in lrc.lines]
            print(_json.dumps(lines, ensure_ascii=False, indent=2))
        else:
            for ln in sorted(lrc.lines, key=lambda x: x.timestamp):
                m, s = divmod(ln.timestamp, 60)
                print(f"[{int(m):02d}:{s:05.2f}] {ln.text}")

    elif args.lyrics_action == "search":
        folder = args.folder or (config_manager.load().music_dirs[0] if config_manager.load().music_dirs else None)
        if not folder:
            logger.error("Please specify folder")
            sys.exit(1)
        kw = args.keyword.lower()
        results = []
        for p in Path(folder).rglob("*.lrc"):
            try:
                text = p.read_text(encoding="utf-8")
                if kw in text.lower():
                    lrc = parse_lrc_file(str(p))
                    matches = [ln for ln in lrc.lines if kw in ln.text.lower()]
                    results.append({
                        "file": str(p), "song": p.stem, "matches": len(matches),
                        "lines": [{"ts": ln.timestamp, "text": ln.text} for ln in matches[:5]],
                    })
            except Exception:
                pass
        if args.json_output:
            print(_json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for r in results:
                print(f"\n{r['song']} ({r['matches']} matches)")
                for ln in r["lines"]:
                    m, s = divmod(ln["ts"], 60)
                    print(f"  [{int(m):02d}:{s:05.2f}] {ln['text']}")


# ============================================================
# config
# ============================================================

def cmd_config(args):
    if args.config_action == "show":
        c = config_manager.load()
        data = {
            "music_dirs": c.music_dirs, "output_lrc_dir": c.output_lrc_dir,
            "api_keys": {
                "groq_configured": bool(c.groq_api_key),
                "xunfei_configured": c.has_xunfei_credentials,
                "deepseek_configured": bool(c.ai_model_api_key),
            },
            "ai": {
                "base_url": c.ai_base_url,
                "model": c.ai_model_name,
                "voice_input_shortcut": c.voice_input_shortcut,
            },
            "asr": {
                "provider": c.asr.provider, "local_model": c.asr.local_model,
                "language": c.asr.language, "use_vocal_separation": c.asr.use_vocal_separation,
                "use_gpu": c.asr.use_gpu,
            },
            "config_path": str(config_manager.config_path),
        }
        _out(data, args)

    elif args.config_action == "set":
        c = config_manager.load()
        try:
            update_config_value(c, args.key, args.value)
        except ValueError as exc:
            logger.error(str(exc))
            sys.exit(1)
        config_manager.config = c
        config_manager.save()
        shown_value = "***" if args.key in (
            "groq_api_key",
            "xunfei_api_key",
            "xunfei_api_secret",
            "ai_model_api_key",
        ) else args.value
        print(f"OK: {args.key} = {shown_value}")

    elif args.config_action == "path":
        print(config_manager.config_path)


def cmd_library(args):
    config = config_manager.load()
    directories_attr = "video_dirs" if args.mode == "video" else "music_dirs"
    select_all_attr = "video_select_all" if args.mode == "video" else "music_select_all"
    directories = list(getattr(config, directories_attr))
    if args.library_action == "list":
        _out({"mode": args.mode, "directories": directories, "select_all": getattr(config, select_all_attr)}, args)
        return
    if args.library_action == "add":
        directory = str(Path(args.folder).expanduser().resolve())
        if not Path(directory).is_dir():
            raise SystemExit(f"Folder not found: {directory}")
        if directory not in directories:
            directories.append(directory)
    elif args.library_action == "remove":
        directory = str(Path(args.folder).expanduser().resolve())
        directories = [item for item in directories if item != directory]
    elif args.library_action == "select-all":
        setattr(config, select_all_attr, args.enabled == "on")
    setattr(config, directories_attr, directories)
    config_manager.config = config
    config_manager.save()
    _out({"mode": args.mode, "directories": directories, "select_all": getattr(config, select_all_attr)}, args)


def cmd_ai(args):
    from core.ai_assistant import AISettings, chat

    config = config_manager.load()
    try:
        answer = chat(
            AISettings(config.ai_model_api_key, config.ai_base_url, config.ai_model_name),
            args.question,
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        raise SystemExit(1) from exc
    _out({"answer": answer} if args.json_output else answer, args)


def cmd_cache(args):
    if args.cache_action == "path":
        print(voice_cache_dir())
    elif args.cache_action == "clear":
        print(f"已清理 {clear_voice_cache()} 个语音缓存文件。")


def cmd_video(args):
    from core.video_aggregation import aggregate_videos_by_time, write_video_transcript_timeline

    folder = str(Path(args.folder).expanduser().resolve())
    config = config_manager.load()
    offset = config.video_time_offsets.get(folder, 0)
    if args.video_action == "calibrate":
        from datetime import datetime

        source = datetime.fromisoformat(args.source)
        target = datetime.fromisoformat(args.target)
        offset = int((target - source).total_seconds())
        config.video_time_offsets[folder] = offset
        config_manager.config = config
        config_manager.save()
        path = write_video_transcript_timeline(folder, offset)
        _out({"offset_seconds": offset, "timeline": str(path)}, args)
    elif args.video_action == "timeline":
        path = write_video_transcript_timeline(folder, offset)
        _out({"timeline": str(path), "offset_seconds": offset}, args)
    else:
        result = aggregate_videos_by_time(folder, offset)
        _out({"output_dir": str(result.output_dir), "video": str(result.video_path)}, args)

# ============================================================
# model
# ============================================================

_MODELS = {
    "tiny":   {"size": "~144 MB", "desc": "Fastest, decent accuracy"},
    "base":   {"size": "~139 MB", "desc": "Recommended, balanced"},
    "small":  {"size": "~922 MB", "desc": "Better, slower"},
    "medium": {"size": "~2.9 GB", "desc": "Best, very slow"},
}

def cmd_model(args):
    cache = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
    if args.model_action == "list":
        models = []
        for name, info in _MODELS.items():
            mf = os.path.join(cache, name + ".pt")
            installed = os.path.exists(mf) and os.path.getsize(mf) > 100_000
            models.append({"name": name, "size": info["size"], "desc": info["desc"],
                           "installed": installed, "path": mf if installed else None})
        _out(models, args)

    elif args.model_action == "info":
        name = args.model_name
        if name not in _MODELS:
            logger.error(f"Unknown model: {name}")
            sys.exit(1)
        info = dict(_MODELS[name])
        info["name"] = name
        mf = os.path.join(cache, name + ".pt")
        info["installed"] = os.path.exists(mf)
        info["path"] = mf
        info["size_on_disk"] = _fmt_size(os.path.getsize(mf)) if info["installed"] else "N/A"
        _out(info, args)

    elif args.model_action == "download":
        name = args.model_name
        if name not in _MODELS:
            logger.error(f"Unknown model: {name}")
            sys.exit(1)
        from PyQt6.QtCore import QCoreApplication
        from ui.settings_dialog import _DownloadWorker
        app = QCoreApplication(sys.argv)
        worker = _DownloadWorker(name)

        def _p(pct, msg): print(f"\r  [{pct:3d}%] {msg}", end="", flush=True)
        def _d(ok, msg):
            print()
            print(f"{'OK' if ok else 'FAIL'}: {msg}")
            app.exit(0 if ok else 1)

        worker.progress.connect(_p)
        worker.finished.connect(_d)
        worker.start()
        sys.exit(app.exec())


# ============================================================
# gpu
# ============================================================

def cmd_gpu(args):
    if args.gpu_action == "scan":
        from core.runtime_detection import detect_hardware, select_runtime

        report = detect_hardware()
        selection = select_runtime(report)
        cuda_ok = False
        try:
            import torch; cuda_ok = torch.cuda.is_available()
        except ImportError:
            pass
        result = {
            "gpu_detected": bool(report.adapters),
            "gpu_name": selection.adapter.name if selection.adapter else None,
            "cuda_installed": cuda_ok,
            "hardware": report.as_dict(),
            "recommended_runtime": selection.as_dict(),
        }
        _out(result, args)

    elif args.gpu_action == "status":
        c = config_manager.load()
        result = {"gpu_enabled": c.asr.use_gpu}
        try:
            import torch
            result["cuda_available"] = torch.cuda.is_available()
            if result["cuda_available"]:
                result["gpu_name"] = torch.cuda.get_device_name(0)
        except ImportError:
            result["cuda_available"] = False
        _out(result, args)


# ============================================================
# sync
# ============================================================

def cmd_sync(args):
    config = config_manager.load()
    if args.sync_action == "compare":
        from core.sync_engine import SyncEngine
        engine = SyncEngine()
        dir_a = args.dir_a or (config.music_dirs[0] if config.music_dirs else None)
        dir_b = args.dir_b or config.sync.remote_dir
        if not dir_a or not dir_b:
            logger.error("Please specify --dir-a and --dir-b")
            sys.exit(1)
        diff = engine.compare_directories(dir_a, dir_b, compare_content=args.strict)
        if args.json_output:
            items = []
            for d in diff:
                items.append({
                    "file": d.file.relative_path,
                    "type": d.diff_type.value,
                    "size_a": d.file.size,
                    "size_b": d.other_file.size if d.other_file else 0,
                })
            print(_json.dumps({"dir_a": dir_a, "dir_b": dir_b, "diff": items, "count": len(diff)},
                              ensure_ascii=False, indent=2))
        else:
            print(f"A: {dir_a}")
            print(f"B: {dir_b}")
            print(f"Differences: {len(diff)}")
            print("-" * 50)
            icons = {"only_in_a": "A>", "only_in_b": "<B", "newer_in_a": "A>", "newer_in_b": "<B", "conflict": "!!"}
            for d in diff:
                dt = d.diff_type.value
                ic = icons.get(dt, "??")
                print(f"  {ic} {d.file.relative_path} [{dt}]")

    elif args.sync_action == "serve":
        folder = args.folder or (config.music_dirs[0] if config.music_dirs else None)
        if not folder:
            logger.error("Please specify folder")
            sys.exit(1)
        from server.http_server import start_http_server
        print(f"Starting HTTP file server...")
        print(f"Folder: {folder}")
        start_http_server(folder)


# ============================================================
# rename
# ============================================================

def cmd_rename(args):
    old = Path(args.file)
    if not old.exists():
        logger.error(f"File not found: {args.file}")
        sys.exit(1)
    new_name = args.new_name
    if not new_name.endswith(old.suffix):
        new_name += old.suffix
    new = old.parent / new_name
    if new.exists():
        logger.error(f"Target exists: {new}")
        sys.exit(1)
    old.rename(new)
    old_lrc = old.with_suffix(".lrc")
    new_lrc = new.with_suffix(".lrc")
    if old_lrc.exists():
        old_lrc.rename(new_lrc)
        print(f"OK: {old.name} -> {new.name} (+ LRC)")
    else:
        print(f"OK: {old.name} -> {new.name}")


# ============================================================
# mark
# ============================================================

def cmd_mark(args):
    fp = Path(args.file).expanduser().resolve()
    if not fp.is_file():
        logger.error(f"File not found: {fp}")
        sys.exit(1)
    root = Path(args.folder).expanduser().resolve() if args.folder else fp.parent
    store = InstrumentalStore(root)
    try:
        store.set_marked(fp, args.mark)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)
    if args.mark:
        print(f"OK: marked as instrumental: {Path(fp).name}")
    else:
        print(f"OK: unmarked: {Path(fp).name}")


# ============================================================
# serve
# ============================================================

def cmd_serve(args):
    if args.serve_action == "http":
        config = config_manager.load()
        folder = config.music_dirs[0] if config.music_dirs else os.getcwd()
        from server.http_server import start_http_server
        print(f"Starting HTTP server...")
        print(f"Folder: {folder}")
        start_http_server(folder)
    elif args.serve_action == "localsend":
        print("LocalSend receiver requires GUI mode.")
        print("  python main.py gui -> Sync -> Start LocalSend receiver")
        sys.exit(1)


# ============================================================
# doctor
# ============================================================

def cmd_doctor(args):
    report = build_environment_report(config_manager.load())
    if args.json_output:
        print(_json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Python: {report['python']}")
        print(f"ffmpeg: {report['ffmpeg']['path'] or 'NOT FOUND'}")
        print(f"Provider: {report['provider']['name']}")
        print(f"Ready: {'YES' if report['ready_for_transcription'] else 'NO'}")
        for issue in report["issues"]:
            print(f"- {issue}")
    if not report["ready_for_transcription"]:
        sys.exit(1)


# ============================================================
# GUI
# ============================================================

def cmd_gui(args):
    import traceback
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from ui.main_window import MainWindow

    def _hook(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error(f"Unhandled exception:\n{tb}")
        QMessageBox.critical(None, "Error", f"Unhandled error:\n\n{exc_value}")
        sys.exit(1)

    sys.excepthook = _hook
    app = QApplication(sys.argv)
    app.setApplicationName("Echovault")
    app.setOrganizationName("Echovault")
    app.setStyle("Fusion")
    try:
        win = MainWindow()
        win.show()
    except Exception as e:
        logger.error(f"Window init failed: {e}")
        QMessageBox.critical(None, "Startup Error", str(e))
        sys.exit(1)
    sys.exit(app.exec())


# ============================================================
# Entry point
# ============================================================

def main():
    p = argparse.ArgumentParser(prog="linlangyuefu", description="Echovault - AI lyrics + file sync")
    sub = p.add_subparsers(dest="command")

    # gui
    sub.add_parser("gui", help="Launch GUI").set_defaults(func=cmd_gui)

    # list
    sp = sub.add_parser("list", help="List songs")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--status", choices=["all","has-lrc","no-lrc","instrumental"], default="all")
    sp.add_argument("--format")
    sp.add_argument("--search")
    sp.add_argument("--json", dest="json_output", action="store_true")
    sp.set_defaults(func=cmd_list)

    # info
    sp = sub.add_parser("info", help="Song detail")
    sp.add_argument("file")
    sp.add_argument("--json", dest="json_output", action="store_true")
    sp.set_defaults(func=cmd_info)

    # transcribe
    sp = sub.add_parser("transcribe", help="Transcribe lyrics")
    sp.add_argument("target")
    sp.add_argument("--language", "-l")
    sp.add_argument("--force", "-f", action="store_true")
    sp.add_argument("--output-dir", "-o")
    sp.add_argument("--provider", "-p")
    sp.add_argument("--json", dest="json_output", action="store_true")
    sp.add_argument("--quiet", "-q", action="store_true")
    sp.set_defaults(func=cmd_transcribe)

    # lyrics
    sp = sub.add_parser("lyrics", help="Lyrics operations")
    s2 = sp.add_subparsers(dest="lyrics_action", required=True)
    x = s2.add_parser("show", help="Show lyrics")
    x.add_argument("file"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_lyrics)
    x = s2.add_parser("search", help="Search lyrics")
    x.add_argument("keyword"); x.add_argument("--folder", "-f"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_lyrics)

    # config
    sp = sub.add_parser("config", help="Configuration")
    s2 = sp.add_subparsers(dest="config_action", required=True)
    x = s2.add_parser("show", help="Show config"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_config)
    x = s2.add_parser("set", help="Set config"); x.add_argument("key"); x.add_argument("value"); x.set_defaults(func=cmd_config)
    x = s2.add_parser("path", help="Config file path"); x.set_defaults(func=cmd_config)

    # library
    sp = sub.add_parser("library", help="Material library folders and selection scope")
    s2 = sp.add_subparsers(dest="library_action", required=True)
    x = s2.add_parser("list", help="List material folders"); x.add_argument("--mode", choices=["music", "video"], default="music"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_library)
    x = s2.add_parser("add", help="Add a material folder"); x.add_argument("folder"); x.add_argument("--mode", choices=["music", "video"], default="music"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_library)
    x = s2.add_parser("remove", help="Remove a material folder"); x.add_argument("folder"); x.add_argument("--mode", choices=["music", "video"], default="music"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_library)
    x = s2.add_parser("select-all", help="Set detail-list scope"); x.add_argument("enabled", choices=["on", "off"]); x.add_argument("--mode", choices=["music", "video"], default="music"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_library)

    # video
    sp = sub.add_parser("video", help="Video material operations")
    s2 = sp.add_subparsers(dest="video_action", required=True)
    x = s2.add_parser("timeline", help="Export video transcript timeline"); x.add_argument("folder"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_video)
    x = s2.add_parser("calibrate", help="Set a video-folder time offset"); x.add_argument("folder"); x.add_argument("--source", required=True, help="YYYY-MM-DDTHH:MM:SS"); x.add_argument("--target", required=True, help="YYYY-MM-DDTHH:MM:SS"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_video)
    x = s2.add_parser("aggregate", help="Aggregate videos by calibrated time"); x.add_argument("folder"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_video)

    # ai
    sp = sub.add_parser("ai", help="Built-in DeepSeek assistant")
    s2 = sp.add_subparsers(dest="ai_action", required=True)
    x = s2.add_parser("chat", help="Ask the assistant with the built-in manual"); x.add_argument("question"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_ai)

    # cache
    sp = sub.add_parser("cache", help="Voice-input cache management")
    s2 = sp.add_subparsers(dest="cache_action", required=True)
    x = s2.add_parser("path", help="Show the voice-input cache folder"); x.set_defaults(func=cmd_cache)
    x = s2.add_parser("clear", help="Delete cached voice recordings"); x.set_defaults(func=cmd_cache)

    # model
    sp = sub.add_parser("model", help="Model management")
    s2 = sp.add_subparsers(dest="model_action", required=True)
    x = s2.add_parser("list", help="List models"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_model)
    x = s2.add_parser("info", help="Model detail"); x.add_argument("model_name"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_model)
    x = s2.add_parser("download", help="Download model"); x.add_argument("model_name"); x.set_defaults(func=cmd_model)

    # gpu
    sp = sub.add_parser("gpu", help="GPU management")
    s2 = sp.add_subparsers(dest="gpu_action", required=True)
    x = s2.add_parser("scan", help="Scan GPU"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_gpu)
    x = s2.add_parser("status", help="GPU status"); x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_gpu)

    # sync
    sp = sub.add_parser("sync", help="File sync")
    s2 = sp.add_subparsers(dest="sync_action", required=True)
    x = s2.add_parser("compare", help="Compare folders"); x.add_argument("--dir-a"); x.add_argument("--dir-b")
    x.add_argument("--strict", action="store_true", help="Compare content hashes when needed")
    x.add_argument("--json", dest="json_output", action="store_true"); x.set_defaults(func=cmd_sync)
    x = s2.add_parser("serve", help="HTTP file server"); x.add_argument("--folder", "-f"); x.set_defaults(func=cmd_sync)

    # rename
    sp = sub.add_parser("rename", help="Rename song (+LRC)")
    sp.add_argument("file"); sp.add_argument("new_name"); sp.set_defaults(func=cmd_rename)

    # mark
    sp = sub.add_parser("mark", help="Mark instrumental")
    sp.add_argument("file"); sp.add_argument("--folder", help="Music library root")
    sp.add_argument("--unmark", dest="mark", action="store_false"); sp.set_defaults(func=cmd_mark, mark=True)

    # serve
    sp = sub.add_parser("serve", help="Start services")
    s2 = sp.add_subparsers(dest="serve_action", required=True)
    x = s2.add_parser("http", help="HTTP file server"); x.set_defaults(func=cmd_serve)
    x = s2.add_parser("localsend", help="LocalSend (needs GUI)"); x.set_defaults(func=cmd_serve)

    # doctor
    sp = sub.add_parser("doctor", help="Check runtime environment")
    sp.add_argument("--json", dest="json_output", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    args = p.parse_args()
    if args.command is None:
        cmd_gui(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
