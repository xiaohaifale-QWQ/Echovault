# MusicSync PyInstaller spec
# 构建命令: pyinstaller MusicSync.spec

# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None

# 需要手动指定的隐藏导入
hidden_imports = [
    # PyQt6
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    # ASR
    'whisper',
    'groq',
    # 音频
    'pydub',
    'mutagen',
    # 同步
    'aiohttp',
    'zeroconf',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MusicSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MusicSync',
)
