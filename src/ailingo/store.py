"""SQLite persistence for prompts, mistake patterns, practice sessions and stats."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .schemas import Example, Exercise, Grade, Pattern

SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    session_id TEXT,
    project TEXT,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    created_at TEXT,
    ingested_at TEXT NOT NULL,
    analyzed_at TEXT,
    skip_reason TEXT,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS prompts_hash ON prompts(text_hash);
CREATE INDEX IF NOT EXISTS prompts_pending ON prompts(analyzed_at, skip_reason, created_at);

CREATE TABLE IF NOT EXISTS ingest_files (
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY(source, path)
);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    correct_form TEXT NOT NULL DEFAULT '',
    tip TEXT NOT NULL DEFAULT '',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    mastery REAL NOT NULL DEFAULT 0.0,
    first_seen TEXT,
    last_seen TEXT,
    last_practiced TEXT,
    times_practiced INTEGER NOT NULL DEFAULT 0,
    times_correct INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    merged_into INTEGER
);

CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY,
    pattern_id INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    prompt_id INTEGER,
    original TEXT NOT NULL,
    corrected TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(pattern_id, original)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    model TEXT,
    prompts_analyzed INTEGER NOT NULL DEFAULT 0,
    findings INTEGER NOT NULL DEFAULT 0,
    typos_ignored INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    model TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    partial INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    xp_earned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    pattern_id INTEGER,
    exercise_json TEXT NOT NULL,
    answer TEXT NOT NULL,
    correct INTEGER NOT NULL,
    score REAL NOT NULL,
    feedback TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def text_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class PromptRow:
    id: int
    source: str
    project: str | None
    text: str
    created_at: datetime | None


@dataclass
class IngestResult:
    source: str
    seen: int = 0
    added: int = 0
    duplicates: int = 0
    non_english: int = 0
    error: str | None = None


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- kv --

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_dt(self, key: str) -> datetime | None:
        return _dt(self.get(key))

    # ------------------------------------------------------------ prompts --

    def file_unchanged(self, source: str, path: Path) -> bool:
        try:
            stat = path.stat()
        except OSError:
            return False
        row = self.conn.execute(
            "SELECT mtime, size FROM ingest_files WHERE source=? AND path=?", (source, str(path))
        ).fetchone()
        return bool(row) and row["mtime"] == stat.st_mtime and row["size"] == stat.st_size

    def mark_file(self, source: str, path: Path) -> None:
        try:
            stat = path.stat()
        except OSError:
            return
        self.conn.execute(
            "INSERT INTO ingest_files(source, path, mtime, size) VALUES(?,?,?,?) "
            "ON CONFLICT(source, path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size",
            (source, str(path), stat.st_mtime, stat.st_size),
        )
        self.conn.commit()

    def add_prompt(
        self,
        *,
        source: str,
        source_id: str,
        session_id: str | None,
        project: str | None,
        text: str,
        language: str,
        created_at: datetime | None,
    ) -> str:
        """Insert a prompt. Returns 'added', 'exists', 'duplicate' or 'non_english'."""
        h = text_hash(text)
        exists = self.conn.execute(
            "SELECT 1 FROM prompts WHERE source=? AND source_id=?", (source, source_id)
        ).fetchone()
        if exists:
            return "exists"
        skip_reason = None
        status = "added"
        if language != "en":
            skip_reason = "non_english"
            status = "non_english"
        elif self.conn.execute("SELECT 1 FROM prompts WHERE text_hash=? LIMIT 1", (h,)).fetchone():
            skip_reason = "duplicate"
            status = "duplicate"
        self.conn.execute(
            "INSERT INTO prompts(source, source_id, session_id, project, text, text_hash, language, "
            "created_at, ingested_at, skip_reason) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                source,
                source_id,
                session_id,
                project,
                text,
                h,
                language,
                created_at.isoformat() if created_at else None,
                now_iso(),
                skip_reason,
            ),
        )
        return status

    def commit(self) -> None:
        self.conn.commit()

    def pending_prompts(self, limit: int | None = None) -> list[PromptRow]:
        sql = (
            "SELECT id, source, project, text, created_at FROM prompts "
            "WHERE analyzed_at IS NULL AND skip_reason IS NULL ORDER BY created_at DESC, id DESC"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [
            PromptRow(r["id"], r["source"], r["project"], r["text"], _dt(r["created_at"]))
            for r in self.conn.execute(sql)
        ]

    def pending_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM prompts WHERE analyzed_at IS NULL AND skip_reason IS NULL"
        ).fetchone()[0]

    def prompt_counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.conn.execute(
            "SELECT source, "
            "SUM(CASE WHEN skip_reason IS NULL THEN 1 ELSE 0 END) AS usable, "
            "SUM(CASE WHEN analyzed_at IS NOT NULL THEN 1 ELSE 0 END) AS analyzed, "
            "COUNT(*) AS total FROM prompts GROUP BY source"
        ):
            out[r["source"]] = {"usable": r["usable"], "analyzed": r["analyzed"], "total": r["total"]}
        return out

    def mark_analyzed(self, prompt_ids: Iterable[int]) -> None:
        ts = now_iso()
        self.conn.executemany(
            "UPDATE prompts SET analyzed_at=? WHERE id=?", [(ts, pid) for pid in prompt_ids]
        )
        self.conn.commit()

    def total_analyzed(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM prompts WHERE analyzed_at IS NOT NULL").fetchone()[0]

    # ----------------------------------------------------------- patterns --

    def _row_to_pattern(self, r: sqlite3.Row) -> Pattern:
        return Pattern(
            id=r["id"],
            key=r["key"],
            category=r["category"],
            title=r["title"],
            description=r["description"],
            correct_form=r["correct_form"],
            tip=r["tip"],
            evidence_count=r["evidence_count"],
            mastery=r["mastery"],
            first_seen=_dt(r["first_seen"]),
            last_seen=_dt(r["last_seen"]),
            last_practiced=_dt(r["last_practiced"]),
            times_practiced=r["times_practiced"],
            times_correct=r["times_correct"],
            archived=bool(r["archived"]),
        )

    def patterns(self, include_archived: bool = False) -> list[Pattern]:
        sql = "SELECT * FROM patterns"
        if not include_archived:
            sql += " WHERE archived=0"
        sql += " ORDER BY evidence_count DESC, last_seen DESC"
        return [self._row_to_pattern(r) for r in self.conn.execute(sql)]

    def pattern_by_key(self, key: str) -> Pattern | None:
        r = self.conn.execute("SELECT * FROM patterns WHERE key=?", (key,)).fetchone()
        return self._row_to_pattern(r) if r else None

    def pattern_by_id(self, pattern_id: int) -> Pattern | None:
        r = self.conn.execute("SELECT * FROM patterns WHERE id=?", (pattern_id,)).fetchone()
        return self._row_to_pattern(r) if r else None

    def resolve_key(self, key: str) -> Pattern | None:
        """Follow merges so findings for an old key land on the canonical pattern."""
        p = self.pattern_by_key(key)
        hops = 0
        while p is not None and p.archived and hops < 10:
            r = self.conn.execute("SELECT merged_into FROM patterns WHERE id=?", (p.id,)).fetchone()
            if not r or r["merged_into"] is None:
                break
            p = self.pattern_by_id(r["merged_into"])
            hops += 1
        return p

    def upsert_pattern(
        self,
        *,
        key: str,
        category: str,
        title: str,
        explanation: str,
        seen_at: datetime | None,
    ) -> Pattern:
        existing = self.resolve_key(key)
        seen = (seen_at or datetime.now(UTC)).isoformat()
        if existing is None:
            self.conn.execute(
                "INSERT INTO patterns(key, category, title, description, correct_form, evidence_count, "
                "first_seen, last_seen) VALUES(?,?,?,?,?,1,?,?)",
                (key, category, title, "", explanation, seen, seen),
            )
            self.conn.commit()
            created = self.pattern_by_key(key)
            assert created is not None
            return created
        # new real-world evidence: bump count, refresh last_seen, and knock mastery down a bit
        self.conn.execute(
            "UPDATE patterns SET evidence_count=evidence_count+1, "
            "last_seen=CASE WHEN last_seen IS NULL OR last_seen < ? THEN ? ELSE last_seen END, "
            "first_seen=CASE WHEN first_seen IS NULL OR first_seen > ? THEN ? ELSE first_seen END, "
            "mastery=MAX(0, mastery*0.9) WHERE id=?",
            (seen, seen, seen, seen, existing.id),
        )
        self.conn.commit()
        refreshed = self.pattern_by_id(existing.id)
        assert refreshed is not None
        return refreshed

    def add_example(
        self, pattern_id: int, prompt_id: int | None, original: str, corrected: str, note: str
    ) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO examples(pattern_id, prompt_id, original, corrected, note, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (pattern_id, prompt_id, original.strip(), corrected.strip(), note.strip(), now_iso()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def examples(self, pattern_id: int, limit: int = 8) -> list[Example]:
        rows = self.conn.execute(
            "SELECT * FROM examples WHERE pattern_id=? ORDER BY id DESC LIMIT ?", (pattern_id, limit)
        )
        return [
            Example(
                id=r["id"],
                pattern_id=r["pattern_id"],
                original=r["original"],
                corrected=r["corrected"],
                note=r["note"],
                created_at=_dt(r["created_at"]),
            )
            for r in rows
        ]

    def update_pattern_text(
        self, pattern_id: int, *, category: str, title: str, description: str, correct_form: str, tip: str
    ) -> None:
        self.conn.execute(
            "UPDATE patterns SET category=?, title=?, description=?, correct_form=?, tip=? WHERE id=?",
            (category, title, description, correct_form, tip, pattern_id),
        )
        self.conn.commit()

    def merge_patterns(self, target_id: int, source_id: int) -> None:
        if target_id == source_id:
            return
        src = self.pattern_by_id(source_id)
        tgt = self.pattern_by_id(target_id)
        if src is None or tgt is None:
            return
        # move examples (ignore collisions)
        for ex in self.conn.execute("SELECT * FROM examples WHERE pattern_id=?", (source_id,)).fetchall():
            self.conn.execute(
                "INSERT OR IGNORE INTO examples(pattern_id, prompt_id, original, corrected, note, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (target_id, ex["prompt_id"], ex["original"], ex["corrected"], ex["note"], ex["created_at"]),
            )
        self.conn.execute("DELETE FROM examples WHERE pattern_id=?", (source_id,))
        self.conn.execute("UPDATE attempts SET pattern_id=? WHERE pattern_id=?", (target_id, source_id))
        first_seen = min(x for x in (src.first_seen, tgt.first_seen) if x) if (src.first_seen or tgt.first_seen) else None
        last_seen = max(x for x in (src.last_seen, tgt.last_seen) if x) if (src.last_seen or tgt.last_seen) else None
        total_practiced = src.times_practiced + tgt.times_practiced
        mastery = (
            (src.mastery * src.times_practiced + tgt.mastery * tgt.times_practiced) / total_practiced
            if total_practiced
            else max(src.mastery, tgt.mastery)
        )
        self.conn.execute(
            "UPDATE patterns SET evidence_count=evidence_count+?, first_seen=?, last_seen=?, "
            "times_practiced=?, times_correct=times_correct+?, mastery=? WHERE id=?",
            (
                src.evidence_count,
                first_seen.isoformat() if first_seen else None,
                last_seen.isoformat() if last_seen else None,
                total_practiced,
                src.times_correct,
                mastery,
                target_id,
            ),
        )
        self.conn.execute(
            "UPDATE patterns SET archived=1, merged_into=?, evidence_count=0 WHERE id=?", (target_id, source_id)
        )
        # re-point anything that was merged into the source
        self.conn.execute("UPDATE patterns SET merged_into=? WHERE merged_into=?", (target_id, source_id))
        self.conn.commit()

    def record_practice(self, pattern_id: int, grade: Grade) -> None:
        p = self.pattern_by_id(pattern_id)
        if p is None:
            return
        if grade.score >= 0.75:
            mastery = min(1.0, p.mastery + 0.18)
        elif grade.score >= 0.4:
            mastery = min(1.0, p.mastery + 0.05)
        else:
            mastery = max(0.0, p.mastery - 0.2)
        self.conn.execute(
            "UPDATE patterns SET mastery=?, last_practiced=?, times_practiced=times_practiced+1, "
            "times_correct=times_correct+? WHERE id=?",
            (mastery, now_iso(), 1 if grade.correct else 0, pattern_id),
        )
        self.conn.commit()

    # ------------------------------------------------------ analysis runs --

    def start_run(self, model: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO analysis_runs(started_at, model) VALUES(?, ?)", (now_iso(), model)
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def finish_run(
        self, run_id: int, *, prompts: int, findings: int, typos: int, status: str, error: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE analysis_runs SET finished_at=?, prompts_analyzed=?, findings=?, typos_ignored=?, "
            "status=?, error=? WHERE id=?",
            (now_iso(), prompts, findings, typos, status, error, run_id),
        )
        self.conn.commit()
        if status == "done":
            self.set("last_analysis_at", now_iso())

    def last_completed_run(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM analysis_runs WHERE status='done' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # ----------------------------------------------------------- sessions --

    def start_session(self, model: str | None, total: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions(started_at, model, total) VALUES(?,?,?)", (now_iso(), model, total)
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def add_attempt(
        self, session_id: int, pattern_id: int | None, exercise: Exercise, answer: str, grade: Grade
    ) -> None:
        self.conn.execute(
            "INSERT INTO attempts(session_id, pattern_id, exercise_json, answer, correct, score, feedback, "
            "created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                session_id,
                pattern_id,
                exercise.model_dump_json(),
                answer,
                1 if grade.correct else 0,
                grade.score,
                grade.feedback,
                now_iso(),
            ),
        )
        self.conn.commit()

    def finish_session(self, session_id: int, *, correct: int, partial: int, score: float, xp: int) -> None:
        self.conn.execute(
            "UPDATE sessions SET finished_at=?, correct=?, partial=?, score=?, xp_earned=? WHERE id=?",
            (now_iso(), correct, partial, score, xp, session_id),
        )
        self.conn.commit()

    def total_xp(self) -> int:
        return int(
            self.conn.execute("SELECT COALESCE(SUM(xp_earned), 0) FROM sessions WHERE finished_at IS NOT NULL").fetchone()[0]
        )

    def session_dates(self) -> set[date]:
        out: set[date] = set()
        for r in self.conn.execute("SELECT finished_at FROM sessions WHERE finished_at IS NOT NULL"):
            dt = _dt(r["finished_at"])
            if dt:
                out.add(dt.astimezone().date())
        return out

    def sessions_completed(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sessions WHERE finished_at IS NOT NULL").fetchone()[0]

    def recent_scores(self, limit: int = 14) -> list[float]:
        rows = self.conn.execute(
            "SELECT score FROM sessions WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r["score"] for r in reversed(rows)]

    def attempts_summary(self) -> tuple[int, int]:
        r = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts").fetchone()
        return int(r[0]), int(r[1])

    def clear_practice_cache(self) -> None:
        self.conn.execute("DELETE FROM kv WHERE key='cached_session'")
        self.conn.commit()

    def cache_session(self, exercises: list[Exercise]) -> None:
        self.set("cached_session", json.dumps([e.model_dump() for e in exercises]))

    def cached_session(self) -> list[Exercise] | None:
        raw = self.get("cached_session")
        if not raw:
            return None
        try:
            return [Exercise.model_validate(e) for e in json.loads(raw)]
        except Exception:
            return None
