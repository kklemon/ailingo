"""Ingest human-written prompts from coding-agent transcripts into the store."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..config import Config
from ..store import IngestResult, Store, now_iso
from .base import RawPrompt, Source, SourceStatus
from .claude_code import ClaudeCodeSource
from .codex import CodexSource
from .filters import prepare
from .opencode import OpenCodeSource

__all__ = [
    "RawPrompt",
    "Source",
    "SourceStatus",
    "all_sources",
    "source_statuses",
    "ingest_all",
]


def all_sources() -> list[Source]:
    return [CodexSource(), ClaudeCodeSource(), OpenCodeSource()]


def source_statuses() -> list[SourceStatus]:
    return [s.status() for s in all_sources()]


def ingest_source(store: Store, source: Source, log: Callable[[str], None] | None = None) -> IngestResult:
    result = IngestResult(source=source.name)
    touched: list[Path] = []

    def unchanged(path: Path) -> bool:
        if store.file_unchanged(source.name, path):
            return True
        touched.append(path)
        return False

    try:
        for raw in source.prompts(unchanged):
            result.seen += 1
            prepared = prepare(raw.text)
            if prepared is None:
                continue
            text, language = prepared
            status = store.add_prompt(
                source=raw.source,
                source_id=raw.source_id,
                session_id=raw.session_id,
                project=raw.project,
                text=text,
                language=language,
                created_at=raw.created_at,
            )
            if status == "added":
                result.added += 1
            elif status == "duplicate":
                result.duplicates += 1
            elif status == "non_english":
                result.non_english += 1
            if result.seen % 500 == 0:
                store.commit()
        store.commit()
        for path in touched:
            store.mark_file(source.name, path)
    except Exception as exc:  # keep other sources going
        result.error = f"{type(exc).__name__}: {exc}"
    if log:
        log(
            f"{source.label}: {result.added} new prompts"
            + (f", {result.duplicates} duplicates" if result.duplicates else "")
            + (f", {result.non_english} non-English" if result.non_english else "")
            + (f" — {result.error}" if result.error else "")
        )
    return result


def ingest_all(store: Store, config: Config, log: Callable[[str], None] | None = None) -> list[IngestResult]:
    results: list[IngestResult] = []
    for source in all_sources():
        if not config.source_enabled(source.name):
            continue
        if not source.status().available:
            continue
        results.append(ingest_source(store, source, log))
    store.set("last_ingest_at", now_iso())
    return results
