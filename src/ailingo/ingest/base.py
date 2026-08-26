from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass
class RawPrompt:
    source: str
    source_id: str
    session_id: str | None
    project: str | None
    text: str
    created_at: datetime | None


@dataclass
class SourceStatus:
    name: str
    label: str
    available: bool
    location: str
    detail: str = ""


class Source(Protocol):
    name: str
    label: str

    def status(self) -> SourceStatus: ...

    def prompts(self, unchanged: FileCheck | None = None) -> Iterator[RawPrompt]: ...


class FileCheck(Protocol):
    """Callback used to skip files that have not changed since the last ingest."""

    def __call__(self, path: Path) -> bool: ...
