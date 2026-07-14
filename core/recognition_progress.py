"""Structured, measurable progress events for lyric recognition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionProgress:
    percent: int
    phase: str
    message: str
    chunk_index: int = 0
    chunk_total: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError("Recognition progress percent must be between 0 and 100")
