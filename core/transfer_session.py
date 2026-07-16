"""Persistent phone-transfer sessions and processing artifact registration."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

TEXT_SNAPSHOT_SUFFIXES = {".lrc", ".txt", ".json", ".csv"}


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class TransferSession:
    session_id: str
    sender: dict[str, Any]
    received_at: str
    workspace: str
    status: str = "received"
    original_files: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    return_history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransferSession":
        return cls(
            session_id=str(data["session_id"]),
            sender=dict(data.get("sender", {})),
            received_at=str(data.get("received_at", "")),
            workspace=str(data.get("workspace", "")),
            status=str(data.get("status", "received")),
            original_files=list(data.get("original_files", [])),
            artifacts=list(data.get("artifacts", [])),
            return_history=list(data.get("return_history", [])),
        )


class TransferSessionManager:
    DEFAULT_ROOT = Path.home() / ".music-lyrics-sync" / "transfers"

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or self.DEFAULT_ROOT)
        self.sessions_dir = self.root / "sessions"
        self.snapshots_dir = self.root / "text-snapshots"

    def create_session(
        self,
        *,
        session_id: str,
        sender: dict[str, Any],
        workspace: str | Path,
        files: list[str | Path],
        received_at: str | None = None,
    ) -> TransferSession:
        workspace_path = Path(workspace).resolve()
        snapshots = self.snapshots_dir / session_id
        original_files: list[dict[str, Any]] = []
        for raw_path in files:
            path = Path(raw_path).resolve()
            if not path.is_file():
                continue
            try:
                relative = str(path.relative_to(workspace_path))
            except ValueError:
                relative = path.name
            stat = path.stat()
            snapshot_path = ""
            if path.suffix.lower() in TEXT_SNAPSHOT_SUFFIXES:
                target = snapshots / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
                snapshot_path = str(target)
            original_files.append(
                {
                    "relative_path": relative,
                    "path": str(path),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "sha256": file_sha256(path),
                    "snapshot_path": snapshot_path,
                }
            )
        session = TransferSession(
            session_id=session_id,
            sender=sender,
            received_at=received_at or datetime.now().astimezone().isoformat(),
            workspace=str(workspace_path),
            original_files=original_files,
        )
        self.save(session)
        return session

    def save(self, session: TransferSession) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{session.session_id}.json"
        temporary = path.with_suffix(".json.tmp")
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(asdict(session), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, session_id: str) -> TransferSession:
        path = self.sessions_dir / f"{session_id}.json"
        return TransferSession.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_sessions(self) -> list[TransferSession]:
        if not self.sessions_dir.exists():
            return []
        sessions = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                sessions.append(
                    TransferSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except (KeyError, OSError, json.JSONDecodeError):
                continue
        return sorted(sessions, key=lambda item: item.received_at, reverse=True)

    def find_session_for_path(self, path: str | Path) -> TransferSession | None:
        candidate = Path(path).resolve()
        for session in self.list_sessions():
            workspace = Path(session.workspace).resolve()
            try:
                candidate.relative_to(workspace)
                return session
            except ValueError:
                continue
        return None

    def register_artifact(
        self,
        source_path: str | Path,
        output_path: str | Path,
        operation: str,
    ) -> bool:
        session = self.find_session_for_path(source_path)
        output = Path(output_path).resolve()
        if session is None or not output.exists():
            return False
        entry = {
            "source_path": str(Path(source_path).resolve()),
            "path": str(output),
            "operation": operation,
            "registered_at": datetime.now().astimezone().isoformat(),
        }
        session.artifacts = [
            item for item in session.artifacts if item.get("path") != entry["path"]
        ]
        session.artifacts.append(entry)
        session.status = "ready_review"
        self.save(session)
        return True

    def record_return(
        self,
        session: TransferSession,
        *,
        device: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        session.return_history.append(
            {
                "device": device,
                "sent_at": datetime.now().astimezone().isoformat(),
                "results": results,
            }
        )
        session.status = (
            "returned"
            if results and all(item.get("status") in {"sent", "skipped"} for item in results)
            else "partially_failed"
        )
        self.save(session)


def register_artifact(
    source_path: str | Path,
    output_path: str | Path,
    operation: str,
) -> bool:
    """Register an output only when its source belongs to a phone-transfer session."""
    try:
        return TransferSessionManager().register_artifact(source_path, output_path, operation)
    except OSError:
        return False
