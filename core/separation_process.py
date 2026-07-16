"""Run Demucs in an isolated CPU or external-CUDA process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .process_utils import hidden_window_kwargs
from .vocal_separation import SeparationCancelled, SeparationError, SeparationResult


def _worker_command(
    input_path: str,
    output_dir: str,
    model: str,
    device: str,
    output_content: str,
    events_file: str,
    denoise: bool = False,
    dereverb: bool = False,
) -> list[str]:
    arguments = [
        "_separate-worker",
        "--input",
        input_path,
        "--output-dir",
        output_dir,
        "--model",
        model,
        "--device",
        device,
        "--output-content",
        output_content,
        "--events-file",
        events_file,
    ]
    if denoise:
        arguments.append("--denoise")
    if dereverb:
        arguments.append("--dereverb")
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), *arguments]


def write_separation_event(events_file: str, payload: dict) -> None:
    with open(events_file, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()


def run_separation_process(
    input_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    model: str,
    device: str,
    output_content: str,
    denoise: bool = False,
    dereverb: bool = False,
    progress=None,
    cancelled=None,
) -> SeparationResult:
    """Run one separation job and stream its JSONL events to the caller."""

    progress = progress or (lambda _percent, _message: None)
    cancelled = cancelled or (lambda: False)
    fd, events_file = tempfile.mkstemp(prefix="echovault_separation_", suffix=".jsonl")
    os.close(fd)
    command = _worker_command(
        str(input_path),
        str(output_dir),
        model,
        device,
        output_content,
        events_file,
        denoise,
        dereverb,
    )
    environment = os.environ.copy()
    environment["HF_HUB_OFFLINE"] = "1"
    working_directory = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    process = subprocess.Popen(
        command,
        cwd=str(working_directory),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_window_kwargs(),
    )
    terminal_event = None
    try:
        with open(events_file, "r", encoding="utf-8") as reader:
            while process.poll() is None:
                if cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise SeparationCancelled("处理已取消")
                while line := reader.readline():
                    event = json.loads(line)
                    if event.get("type") == "progress":
                        progress(int(event["percent"]), str(event["message"]))
                    elif event.get("type") in {"result", "error"}:
                        terminal_event = event
                time.sleep(0.05)
            while line := reader.readline():
                event = json.loads(line)
                if event.get("type") == "progress":
                    progress(int(event["percent"]), str(event["message"]))
                elif event.get("type") in {"result", "error"}:
                    terminal_event = event

        stderr = process.stderr.read() if process.stderr else ""
        if not terminal_event:
            detail = stderr.strip()[-800:] or f"子进程退出码 {process.returncode}"
            raise SeparationError(f"人声分离进程异常退出：{detail}")
        if terminal_event["type"] == "error":
            raise SeparationError(str(terminal_event.get("message") or "人声分离失败"))
        return SeparationResult(
            Path(terminal_event["vocals_path"])
            if terminal_event.get("vocals_path")
            else None,
            Path(terminal_event["accompaniment_path"])
            if terminal_event.get("accompaniment_path")
            else None,
            int(terminal_event["sample_rate"]),
        )
    finally:
        if process.poll() is None:
            process.kill()
        Path(events_file).unlink(missing_ok=True)
