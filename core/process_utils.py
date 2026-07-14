"""Subprocess helpers shared by the Windows desktop application."""

from __future__ import annotations

import os
import subprocess


def hidden_window_kwargs() -> dict:
    """Return Windows-only kwargs that prevent a console window from flashing."""
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }
