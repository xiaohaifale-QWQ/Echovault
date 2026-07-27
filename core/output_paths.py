"""Safe output-path helpers for destructive media operations."""

from __future__ import annotations

import os
from pathlib import Path


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def unique_output_path(
    requested_path: str | Path,
    input_paths: list[str] | tuple[str, ...] = (),
) -> str:
    """Return a path that neither overwrites an input nor an existing result."""

    requested = Path(requested_path)
    protected = {_path_key(path) for path in input_paths if path}
    candidate = requested
    if _path_key(candidate) in protected:
        candidate = candidate.with_name(
            f"{candidate.stem}_edited{candidate.suffix}"
        )

    base = candidate
    index = 2
    while candidate.exists() or _path_key(candidate) in protected:
        candidate = base.with_name(f"{base.stem}_{index}{base.suffix}")
        index += 1
    return str(candidate)
