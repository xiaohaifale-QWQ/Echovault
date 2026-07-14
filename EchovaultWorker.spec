# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for a separately downloadable ASR Worker runtime."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH)
hidden_imports = [
    "torch",
    "whisper",
    "core.whisper_loader",
] + collect_submodules("whisper") + collect_submodules("tiktoken_ext")

datas = collect_data_files("certifi") + collect_data_files("whisper")

a = Analysis(
    [str(project_root / "worker" / "asr_worker.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["demucs", "matplotlib", "pandas", "PIL", "torchvision", "torchaudio"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="echovault-asr-worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="echovault-asr-worker",
)
