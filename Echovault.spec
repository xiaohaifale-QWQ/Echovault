# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the Windows desktop application."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH)
ffmpeg_path = os.environ.get("ECHOVAULT_FFMPEG", "")
if not ffmpeg_path or not Path(ffmpeg_path).is_file():
    raise SystemExit(
        "ECHOVAULT_FFMPEG must point to an existing ffmpeg executable. "
        "Use build.ps1 to configure it automatically."
    )
ffprobe_path = os.environ.get("ECHOVAULT_FFPROBE", "")
if not ffprobe_path or not Path(ffprobe_path).is_file():
    raise SystemExit(
        "ECHOVAULT_FFPROBE must point to an existing ffprobe executable. "
        "Use build.ps1 to configure it automatically."
    )

hidden_imports = [
    "groq",
    "opencc",
    "PyQt6.QtMultimedia",
    "torch",
    "zeroconf",
] + collect_submodules("groq") + collect_submodules("whisper") + collect_submodules("tiktoken_ext")

datas = collect_data_files("certifi") + collect_data_files("whisper")
binaries = [(ffmpeg_path, "."), (ffprobe_path, ".")]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "demucs",
        "matplotlib",
        "pandas",
        "PIL",
        "psutil",
        "torchaudio",
        "torchvision",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Echovault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=os.environ.get("ECHOVAULT_CONSOLE") == "1",
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Echovault",
)
