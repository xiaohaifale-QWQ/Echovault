# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the cloud-first Windows MVP."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


project_root = Path(SPECPATH)
ffmpeg_path = os.environ.get("ECHOVAULT_FFMPEG", "")
if not ffmpeg_path or not Path(ffmpeg_path).is_file():
    raise SystemExit(
        "ECHOVAULT_FFMPEG must point to an existing ffmpeg executable. "
        "Use build.ps1 to configure it automatically."
    )

hidden_imports = [
    "groq",
    "opencc",
    "zeroconf",
]

datas = collect_data_files("certifi")
binaries = [(ffmpeg_path, ".")]

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
        "numpy",
        "pandas",
        "PIL",
        "psutil",
        "torch",
        "torchaudio",
        "torchvision",
        "whisper",
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
    console=False,
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
