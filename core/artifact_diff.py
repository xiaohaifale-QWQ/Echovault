"""Compare a received phone-transfer baseline with its current processing results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.transfer_session import TransferSession, file_sha256

EXCLUDED_SUFFIXES = {".part", ".tmp", ".pyc"}
EXCLUDED_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass(frozen=True)
class ArtifactDiff:
    path: str
    relative_path: str
    status: str
    size: int
    operation: str = ""
    original_path: str = ""
    snapshot_path: str = ""
    returned: bool = False

    @property
    def recommended(self) -> bool:
        return self.status in {"generated", "modified"} and not self.returned


def _is_excluded(path: Path) -> bool:
    return (
        path.suffix.lower() in EXCLUDED_SUFFIXES
        or any(part in EXCLUDED_NAMES for part in path.parts)
        or path.name.startswith(".echovault-")
        or path.name.endswith(".bak")
    )


def scan_session_diffs(
    session: TransferSession,
    *,
    strict_hash: bool = True,
) -> list[ArtifactDiff]:
    workspace = Path(session.workspace)
    baseline = {item["relative_path"]: item for item in session.original_files}
    artifacts = {
        str(Path(item.get("path", "")).resolve()): item
        for item in session.artifacts
        if item.get("path")
    }
    artifact_sources = {
        str(Path(item.get("original_output_path", "")).resolve())
        for item in session.artifacts
        if item.get("original_output_path")
    }
    returned_paths = {
        str(Path(result["path"]).resolve())
        for history in session.return_history
        for result in history.get("results", [])
        if result.get("status") in {"sent", "skipped"} and result.get("path")
    }
    current: dict[str, Path] = {}
    if workspace.exists():
        for path in workspace.rglob("*"):
            if path.is_file() and not _is_excluded(path):
                current[str(path.relative_to(workspace))] = path

    diffs: list[ArtifactDiff] = []
    for relative_path, original in baseline.items():
        path = current.pop(relative_path, None)
        if path is None:
            diffs.append(
                ArtifactDiff(
                    path=original.get("path", ""),
                    relative_path=relative_path,
                    status="missing",
                    size=0,
                    original_path=original.get("path", ""),
                    snapshot_path=original.get("snapshot_path", ""),
                )
            )
            continue
        changed = path.stat().st_size != int(original.get("size", 0))
        if strict_hash and not changed:
            changed = file_sha256(path) != original.get("sha256", "")
        absolute = str(path.resolve())
        if absolute in artifact_sources:
            continue
        diffs.append(
            ArtifactDiff(
                path=absolute,
                relative_path=relative_path,
                status="modified" if changed else "unchanged",
                size=path.stat().st_size,
                original_path=original.get("path", ""),
                snapshot_path=original.get("snapshot_path", ""),
                returned=absolute in returned_paths,
            )
        )

    for relative_path, path in current.items():
        absolute = str(path.resolve())
        if absolute in artifact_sources:
            continue
        metadata = artifacts.get(absolute, {})
        diffs.append(
            ArtifactDiff(
                path=absolute,
                relative_path=relative_path,
                status="generated",
                size=path.stat().st_size,
                operation=str(metadata.get("operation", "")),
                returned=absolute in returned_paths,
            )
        )

    workspace_paths = {str(path.resolve()) for path in current.values()}
    workspace_paths.update(
        str((workspace / item["relative_path"]).resolve()) for item in session.original_files
    )
    for absolute, metadata in artifacts.items():
        path = Path(absolute)
        if absolute in workspace_paths or not path.is_file() or _is_excluded(path):
            continue
        diffs.append(
            ArtifactDiff(
                path=absolute,
                relative_path=path.name,
                status="generated",
                size=path.stat().st_size,
                operation=str(metadata.get("operation", "")),
                returned=absolute in returned_paths,
            )
        )

    order = {"generated": 0, "modified": 1, "missing": 2, "unchanged": 3}
    return sorted(diffs, key=lambda item: (order.get(item.status, 9), item.relative_path.lower()))
