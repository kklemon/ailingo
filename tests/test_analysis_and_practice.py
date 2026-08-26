import pytest

from ailingo.analysis import analysis_is_due, analyze_pending
from ailingo.config import Config
from ailingo.practice import SessionRunner, generate_session
from ailingo.store import Store

from .fakes import install


@pytest.fixture
def fake_llm(monkeypatch):
    install(monkeypatch)


def _prompts(store: Store, n: int = 3) -> None:
    for i in range(n):
        store.add_prompt(source="codex", source_id=str(i), session_id=None, project=None,
                         text=f"Please add test for parser number {i} which has then a field", language="en", created_at=None)


async def test_analyze_pending_builds_patterns(store: Store, config: Config, fake_llm):
    _prompts(store)
    assert analysis_is_due(store, config, min_new_prompts=1)
    report = await analyze_pending(store, config, max_prompts=10)
    assert report.prompts_analyzed == 3
    assert report.typos_ignored == 1
    assert report.findings == 2
    assert store.pending_count() == 0
    keys = {p.key for p in store.patterns()}
    assert keys == {"missing_article", "german_word_order"}
    p = store.pattern_by_key("missing_article")
    assert "articles" in p.title.lower() and p.tip
    assert store.get_dt("last_analysis_at") is not None
    assert not analysis_is_due(store, config, min_new_prompts=1)


async def test_session_flow(store: Store, config: Config, fake_llm):
    _prompts(store)
    await analyze_pending(store, config, max_prompts=10)
    exercises = await generate_session(store, config, 3)
    assert len(exercises) == 3
    runner = SessionRunner(store, config, exercises)
    for i, ex in enumerate(exercises):
        if ex.kind == "multiple_choice":
            grade = await runner.submit(i, ex.answer)
            assert grade.correct
        elif ex.kind == "fill_gap":
            grade = await runner.submit(i, "a")
            assert grade.correct
        else:
            grade = await runner.submit(i, "The endpoint then returns list of users.")
            assert grade.score == 0.5
    summary = runner.finish()
    assert summary.total == 3 and summary.correct == 2 and summary.partial == 1
    assert summary.xp_earned == 25 and summary.streak == 1 and summary.streak_extended
    assert store.sessions_completed() == 1
    assert store.pattern_by_key("missing_article").times_practiced == 2
