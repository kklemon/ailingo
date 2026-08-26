"""OpenCode: SQLite database under the XDG data dir (~/.local/share/opencode/opencode.db)."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from .base import FileCheck, RawPrompt, SourceStatus


class OpenCodeSource:
    name = "opencode"
    label = "OpenCode"

    def __init__(self, db: Path | None = None):
        if db is not None:
            self.db = db
        else:
            xdg = os.environ.get("XDG_DATA_HOME")
            base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
            self.db = base / "opencode" / "opencode.db"

    def status(self) -> SourceStatus:
        if not self.db.exists():
            return SourceStatus(self.name, self.label, False, str(self.db), "not found")
        try:
            with self._connect() as conn:
                n = conn.execute(
                    "SELECT COUNT(*) FROM message WHERE json_extract(data, '$.role') = 'user'"
                ).fetchone()[0]
            return SourceStatus(self.name, self.label, True, str(self.db), f"{n} user messages")
        except sqlite3.Error as exc:
            return SourceStatus(self.name, self.label, False, str(self.db), f"unreadable: {exc}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def prompts(self, unchanged: FileCheck | None = None) -> Iterator[RawPrompt]:
        if not self.db.exists():
            return
        try:
            conn = self._connect()
        except sqlite3.Error:
            return
        try:
            rows = conn.execute(
                "SELECT p.id, p.session_id, p.time_created, p.data AS part, s.directory "
                "FROM part p JOIN message m ON m.id = p.message_id "
                "LEFT JOIN session s ON s.id = p.session_id "
                "WHERE json_extract(m.data, '$.role') = 'user' AND json_extract(p.data, '$.type') = 'text' "
                "ORDER BY p.time_created"
            ).fetchall()
        except sqlite3.Error:
            conn.close()
            return
        try:
            for r in rows:
                try:
                    part = json.loads(r["part"])
                except json.JSONDecodeError:
                    continue
                if part.get("synthetic") or part.get("ignored"):
                    continue
                text = part.get("text")
                if not isinstance(text, str):
                    continue
                ts = r["time_created"]
                created = datetime.fromtimestamp(ts / 1000, tz=UTC) if isinstance(ts, int | float) else None
                yield RawPrompt(
                    source=self.name,
                    source_id=str(r["id"]),
                    session_id=r["session_id"],
                    project=r["directory"],
                    text=text,
                    created_at=created,
                )
        finally:
            conn.close()
