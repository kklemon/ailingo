import json
import sqlite3
from pathlib import Path

from ailingo.config import Config
from ailingo.ingest import ingest_source
from ailingo.ingest.claude_code import ClaudeCodeSource
from ailingo.ingest.codex import CodexSource
from ailingo.ingest.opencode import OpenCodeSource
from ailingo.store import Store


def test_codex_history(tmp_path: Path, store: Store):
    home = tmp_path / ".codex"
    home.mkdir()
    lines = [
        {"session_id": "s1", "ts": 1758052687, "text": "Adapt the translation texts of the cookie consent script"},
        {"session_id": "s1", "ts": 1758052700, "text": "Adapt the translation texts of the cookie consent script"},
        {"session_id": "s2", "ts": 1758052800, "text": "Mache den Bericht ausführlicher und persönlicher bitte"},
        {"session_id": "s2", "ts": 1758052900, "text": "/status"},
    ]
    (home / "history.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    src = CodexSource(home)
    assert src.status().available
    result = ingest_source(store, src)
    assert result.added == 1
    assert result.duplicates == 1
    assert result.non_english == 1
    assert store.pending_count() == 1


def test_codex_sessions_fallback(tmp_path: Path, store: Store):
    home = tmp_path / ".codex"
    day = home / "sessions" / "2026" / "01" / "01"
    day.mkdir(parents=True)
    rows = [
        {"timestamp": "2026-01-01T10:00:00.000Z", "type": "session_meta", "payload": {"id": "abc", "cwd": "/proj"}},
        {"timestamp": "2026-01-01T10:00:01.000Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Please refactor the camera manager into smaller modules", "kind": "plain"}},
        {"timestamp": "2026-01-01T10:00:02.000Z", "type": "event_msg", "payload": {"type": "agent_message", "message": "Sure"}},
    ]
    (day / "rollout-1.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    result = ingest_source(store, CodexSource(home))
    assert result.added == 1
    row = store.pending_prompts()[0]
    assert row.project == "/proj"
    # second ingest skips the unchanged file
    result2 = ingest_source(store, CodexSource(home))
    assert result2.seen == 0


def test_claude_code_transcripts(tmp_path: Path, store: Store):
    home = tmp_path / ".claude"
    proj = home / "projects" / "-Users-me-proj"
    proj.mkdir(parents=True)
    rows = [
        {"type": "user", "uuid": "u1", "sessionId": "s", "cwd": "/me/proj", "timestamp": "2026-08-08T21:00:38.411Z",
         "message": {"role": "user", "content": "Give the table a bit more air to breadth, it's too compact"}},
        {"type": "user", "uuid": "u2", "isMeta": True, "message": {"role": "user", "content": "meta stuff that is long enough"}},
        {"type": "user", "uuid": "u3", "isSidechain": True, "message": {"role": "user", "content": "subagent prompt that is long enough"}},
        {"type": "user", "uuid": "u4", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "user", "uuid": "u5", "message": {"role": "user", "content": "<task-notification>done</task-notification>"}},
        {"type": "user", "uuid": "u6", "message": {"role": "user", "content": [{"type": "text", "text": "<system-reminder>x</system-reminder>\nAlso add unit tests for the parser module"}]}},
        {"type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}},
    ]
    (proj / "sess.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    (proj / "sess").mkdir()
    (proj / "sess" / "subagents").mkdir()
    (proj / "sess" / "subagents" / "agent-1.jsonl").write_text(json.dumps(rows[0]) + "\n")
    src = ClaudeCodeSource(home)
    result = ingest_source(store, src)
    assert result.added == 2
    texts = [r.text for r in store.pending_prompts()]
    assert any("unit tests" in t for t in texts)
    assert all("system-reminder" not in t for t in texts)


def test_opencode_db(tmp_path: Path, store: Store):
    db = tmp_path / "opencode" / "opencode.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE session(id TEXT PRIMARY KEY, directory TEXT);
        CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
        CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
        INSERT INTO session VALUES('s1', '/work');
        INSERT INTO message VALUES('m1', 's1', 1787047340328, '{"role":"user"}');
        INSERT INTO message VALUES('m2', 's1', 1787047340344, '{"role":"assistant"}');
        INSERT INTO part VALUES('p1', 'm1', 's1', 1787047340333, '{"type":"text","text":"Create a slick landing page as a single HTML file"}');
        INSERT INTO part VALUES('p2', 'm1', 's1', 1787047340334, '{"type":"text","text":"<system-reminder>sel</system-reminder>","synthetic":true}');
        INSERT INTO part VALUES('p3', 'm2', 's1', 1787047340335, '{"type":"text","text":"Sure thing, here is the page for you"}');
        """
    )
    conn.commit()
    conn.close()
    src = OpenCodeSource(db)
    assert src.status().available
    result = ingest_source(store, src)
    assert result.added == 1
    row = store.pending_prompts()[0]
    assert row.project == "/work" and row.created_at is not None


def test_ingest_all_respects_disabled_sources(tmp_path: Path, store: Store, monkeypatch):
    from ailingo import ingest as ing

    calls = []
    monkeypatch.setattr(ing, "all_sources", lambda: [CodexSource(tmp_path / "nope")])
    cfg = Config(sources={"codex": False})
    assert ing.ingest_all(store, cfg, calls.append) == []
