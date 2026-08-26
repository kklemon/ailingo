"""OpenAI Codex CLI: ~/.codex/history.jsonl (fallback: session rollouts)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from .base import FileCheck, RawPrompt, SourceStatus


class CodexSource:
    name = "codex"
    label = "Codex CLI"

    def __init__(self, home: Path | None = None):
        env = os.environ.get("CODEX_HOME")
        self.home = home or (Path(env).expanduser() if env else Path.home() / ".codex")

    @property
    def history_path(self) -> Path:
        return self.home / "history.jsonl"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    def status(self) -> SourceStatus:
        if self.history_path.exists():
            try:
                n = sum(1 for _ in self.history_path.open("rb"))
            except OSError:
                n = 0
            return SourceStatus(self.name, self.label, True, str(self.history_path), f"{n} history entries")
        if self.sessions_dir.exists():
            n = sum(1 for _ in self.sessions_dir.rglob("*.jsonl"))
            return SourceStatus(self.name, self.label, True, str(self.sessions_dir), f"{n} session files")
        return SourceStatus(self.name, self.label, False, str(self.home), "not found")

    def prompts(self, unchanged: FileCheck | None = None) -> Iterator[RawPrompt]:
        if self.history_path.exists():
            yield from self._from_history()
        elif self.sessions_dir.exists():
            yield from self._from_sessions(unchanged)

    def _from_history(self) -> Iterator[RawPrompt]:
        # history.jsonl is append-only: we always rescan it (cheap) and rely on source_id de-dup
        with self.history_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = d.get("text")
                if not isinstance(text, str):
                    continue
                ts = d.get("ts")
                created = datetime.fromtimestamp(ts, tz=UTC) if isinstance(ts, int | float) else None
                sid = str(d.get("session_id") or "")
                digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
                yield RawPrompt(
                    source=self.name,
                    source_id=f"{sid}:{ts}:{digest}",
                    session_id=sid or None,
                    project=None,
                    text=text,
                    created_at=created,
                )

    def _from_sessions(self, unchanged: FileCheck | None) -> Iterator[RawPrompt]:
        for path in sorted(self.sessions_dir.rglob("*.jsonl")):
            if unchanged and unchanged(path):
                continue
            cwd: str | None = None
            session_id: str | None = None
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh):
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        payload = d.get("payload") or {}
                        if d.get("type") == "session_meta":
                            cwd = payload.get("cwd")
                            session_id = payload.get("id")
                            continue
                        if d.get("type") != "event_msg" or payload.get("type") != "user_message":
                            continue
                        if payload.get("kind") not in (None, "plain"):
                            continue
                        text = payload.get("message")
                        if not isinstance(text, str):
                            continue
                        yield RawPrompt(
                            source=self.name,
                            source_id=f"{path.stem}:{i}",
                            session_id=session_id,
                            project=cwd,
                            text=text,
                            created_at=_parse_ts(d.get("timestamp")),
                        )
            except OSError:
                continue


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
