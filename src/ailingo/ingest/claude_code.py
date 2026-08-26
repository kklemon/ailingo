"""Claude Code: ~/.claude/projects/<project>/<session>.jsonl transcripts."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from .base import FileCheck, RawPrompt, SourceStatus


class ClaudeCodeSource:
    name = "claude_code"
    label = "Claude Code"

    def __init__(self, home: Path | None = None):
        env = os.environ.get("CLAUDE_CONFIG_DIR")
        self.home = home or (Path(env).expanduser() if env else Path.home() / ".claude")

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    def _files(self) -> list[Path]:
        if not self.projects_dir.exists():
            return []
        return sorted(p for p in self.projects_dir.glob("*/*.jsonl") if p.is_file())

    def status(self) -> SourceStatus:
        files = self._files()
        if not files:
            return SourceStatus(self.name, self.label, False, str(self.projects_dir), "not found")
        return SourceStatus(self.name, self.label, True, str(self.projects_dir), f"{len(files)} session files")

    def prompts(self, unchanged: FileCheck | None = None) -> Iterator[RawPrompt]:
        for path in self._files():
            if unchanged and unchanged(path):
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh):
                        yield from self._parse_line(path, i, line)
            except OSError:
                continue

    def _parse_line(self, path: Path, index: int, line: str) -> Iterator[RawPrompt]:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return
        if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
            return
        message = d.get("message") or {}
        if message.get("role") != "user":
            return
        content = message.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
        if not texts:
            return
        text = "\n\n".join(texts)
        uuid = d.get("uuid") or f"{path.stem}:{index}"
        yield RawPrompt(
            source=self.name,
            source_id=str(uuid),
            session_id=d.get("sessionId") or path.stem,
            project=d.get("cwd"),
            text=text,
            created_at=_parse_ts(d.get("timestamp")),
        )


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
