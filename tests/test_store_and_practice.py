import random
from datetime import UTC, date, datetime, timedelta

from ailingo.gamification import compute_streak, level_for
from ailingo.practice import grade_locally, pattern_weight, select_patterns, xp_for
from ailingo.schemas import Exercise, Grade
from ailingo.store import Store


def _seed(store: Store) -> None:
    now = datetime.now(UTC)
    for key, n in (("missing_article", 5), ("german_word_order", 2), ("comma_splice", 1)):
        for i in range(n):
            p = store.upsert_pattern(key=key, category="grammar", title=key, explanation="rule", seen_at=now - timedelta(days=i))
            store.add_example(p.id, None, f"orig {key} {i}", f"fixed {key} {i}", "note")


def test_upsert_counts_and_examples(store: Store):
    _seed(store)
    p = store.pattern_by_key("missing_article")
    assert p is not None and p.evidence_count == 5
    assert len(store.examples(p.id)) == 5
    # duplicate example is ignored
    assert not store.add_example(p.id, None, "orig missing_article 0", "x", "")


def test_merge_patterns_moves_everything(store: Store):
    _seed(store)
    a = store.pattern_by_key("missing_article")
    b = store.pattern_by_key("german_word_order")
    store.merge_patterns(a.id, b.id)
    a2 = store.pattern_by_id(a.id)
    assert a2.evidence_count == 7
    assert len(store.examples(a.id, limit=20)) == 7
    assert store.pattern_by_id(b.id).archived
    assert store.resolve_key("german_word_order").id == a.id
    assert [p.key for p in store.patterns()] == ["missing_article", "comma_splice"]
    # new evidence for the merged key lands on the canonical pattern
    store.upsert_pattern(key="german_word_order", category="grammar", title="t", explanation="e", seen_at=None)
    assert store.pattern_by_id(a.id).evidence_count == 8


def test_new_evidence_lowers_mastery(store: Store):
    _seed(store)
    p = store.pattern_by_key("comma_splice")
    store.record_practice(p.id, Grade(correct=True, score=1.0, feedback=""))
    assert store.pattern_by_id(p.id).mastery > 0
    before = store.pattern_by_id(p.id).mastery
    store.upsert_pattern(key="comma_splice", category="grammar", title="t", explanation="e", seen_at=None)
    assert store.pattern_by_id(p.id).mastery < before


def test_select_patterns_prefers_heavy_unmastered(store: Store):
    _seed(store)
    rng = random.Random(1)
    counts = {}
    for _ in range(200):
        for p in select_patterns(store, 1, rng):
            counts[p.key] = counts.get(p.key, 0) + 1
    assert counts["missing_article"] > counts["comma_splice"]
    slots = select_patterns(store, 6, rng)
    assert len(slots) == 6 and len({p.key for p in slots}) == 3


def test_pattern_weight_spacing(store: Store):
    _seed(store)
    p = store.pattern_by_key("missing_article")
    now = datetime.now(UTC)
    w = pattern_weight(p, now)
    store.record_practice(p.id, Grade(correct=True, score=1.0, feedback=""))
    assert pattern_weight(store.pattern_by_id(p.id), now) < w


def test_grade_locally():
    mc = Exercise(kind="multiple_choice", pattern_key="k", prompt="?", options=["a", "the", "an"], answer="the", explanation="e")
    assert grade_locally(mc, "the").correct
    assert not grade_locally(mc, "a").correct
    gap = Exercise(kind="fill_gap", pattern_key="k", prompt="?", text="I'm trying ___ reproduce", answer="to", accepted=[], explanation="e")
    assert grade_locally(gap, " To ").correct
    assert grade_locally(gap, "for") is None  # needs the model
    fix = Exercise(kind="correct_sentence", pattern_key="k", prompt="?", text="Add test", answer="Add a test.", explanation="e")
    assert grade_locally(fix, "add a test").correct
    assert grade_locally(fix, "Add test") is None
    assert not grade_locally(fix, "").correct


def test_xp_levels_streak():
    assert xp_for(Grade(correct=True, score=1.0, feedback="")) == 10
    assert xp_for(Grade(correct=False, score=0.5, feedback="")) == 5
    assert xp_for(Grade(correct=False, score=0.0, feedback="")) == 1
    assert level_for(0)[0] == 1 and level_for(45)[0] == 2
    today = date(2026, 8, 26)
    days = {today, today - timedelta(days=1), today - timedelta(days=2), today - timedelta(days=5)}
    assert compute_streak(days, today) == 3
    assert compute_streak({today - timedelta(days=1)}, today) == 1
    assert compute_streak({today - timedelta(days=2)}, today) == 0
    assert compute_streak(set(), today) == 0


def test_prompt_dedupe_across_sources(store: Store):
    a = store.add_prompt(source="codex", source_id="1", session_id=None, project=None, text="Fix the  bug", language="en", created_at=None)
    b = store.add_prompt(source="claude_code", source_id="2", session_id=None, project=None, text="fix the bug", language="en", created_at=None)
    c = store.add_prompt(source="codex", source_id="1", session_id=None, project=None, text="whatever", language="en", created_at=None)
    assert (a, b, c) == ("added", "duplicate", "exists")
    assert store.pending_count() == 1
