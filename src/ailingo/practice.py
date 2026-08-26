"""Daily practice: pick weak spots, generate exercises, grade answers, book results."""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .config import Config
from .gamification import compute_streak, level_for
from .llm import prompts as P
from .llm.client import LLMError, build_model, make_agent
from .schemas import Exercise, ExerciseSet, Grade, Pattern, SessionSummary
from .store import Store

XP_CORRECT = 10
XP_PARTIAL = 5
XP_WRONG = 1
XP_PERFECT_BONUS = 15


def pattern_weight(p: Pattern, now: datetime) -> float:
    if p.archived:
        return 0.0
    weight = math.sqrt(max(p.evidence_count, 1)) * (1.15 - p.mastery)
    if p.last_seen and now - p.last_seen < timedelta(days=30):
        weight *= 1.4
    if p.last_practiced:
        age = now - p.last_practiced
        if age < timedelta(hours=20):
            weight *= 0.35
        elif age < timedelta(days=3):
            weight *= 0.7
    return max(weight, 0.01)


def select_patterns(store: Store, count: int, rng: random.Random | None = None) -> list[Pattern]:
    """Weighted choice of patterns for a session; returns one entry per exercise slot."""
    rng = rng or random.Random()
    now = datetime.now(UTC)
    patterns = store.patterns()
    if not patterns:
        return []
    weights = [pattern_weight(p, now) for p in patterns]
    slots: list[Pattern] = []
    pool = list(zip(patterns, weights, strict=True))
    # first pass: distinct patterns, weighted without replacement
    while pool and len(slots) < count:
        total = sum(w for _, w in pool)
        r = rng.uniform(0, total)
        acc = 0.0
        for i, (p, w) in enumerate(pool):
            acc += w
            if acc >= r:
                slots.append(p)
                pool.pop(i)
                break
    # second pass: if fewer patterns than slots, repeat the heaviest ones
    while len(slots) < count:
        slots.append(rng.choices(patterns, weights=weights, k=1)[0])
    return slots


def _format_patterns_for_exercises(store: Store, slots: list[Pattern]) -> str:
    counts: dict[int, int] = {}
    order: list[Pattern] = []
    for p in slots:
        if p.id not in counts:
            order.append(p)
        counts[p.id] = counts.get(p.id, 0) + 1
    lines = [f"Create exactly {len(slots)} exercises in total.", ""]
    for p in order:
        lines.append(f"### pattern_key: {p.key}  (make {counts[p.id]} exercise(s) for this pattern)")
        lines.append(f"title: {p.title} | category: {p.category}")
        if p.description:
            lines.append(f"habit: {p.description}")
        if p.correct_form:
            lines.append(f"rule: {p.correct_form}")
        for ex in store.examples(p.id, limit=3):
            lines.append(f'- writer wrote "{ex.original}" — should be "{ex.corrected}"')
        lines.append("")
    return "\n".join(lines)


async def generate_session(store: Store, config: Config, count: int | None = None) -> list[Exercise]:
    n = count or config.exercises_per_session
    slots = select_patterns(store, n)
    if not slots:
        raise LLMError("No mistake patterns yet. Run a sync first so I can read your prompts.")
    model = build_model(config)
    agent = make_agent(model, ExerciseSet, P.EXERCISE_WRITER)
    result = await agent.run(_format_patterns_for_exercises(store, slots))
    exercises = [e for e in result.output.exercises if _valid_exercise(e)]
    known = {p.key for p in slots}
    for e in exercises:
        if e.pattern_key not in known:
            resolved = store.resolve_key(e.pattern_key)
            e.pattern_key = resolved.key if resolved else slots[0].key
    if not exercises:
        raise LLMError("The model returned no usable exercises. Try again.")
    random.shuffle(exercises)
    return exercises[:n]


def _valid_exercise(e: Exercise) -> bool:
    if not e.prompt.strip() or not e.answer.strip():
        return False
    if e.kind == "multiple_choice":
        if len(e.options) < 2:
            return False
        if e.answer not in e.options:
            # tolerate case/space differences
            match = [o for o in e.options if _norm(o) == _norm(e.answer)]
            if not match:
                return False
            e.answer = match[0]
    if e.kind == "fill_gap" and "___" not in e.text:
        return False
    if e.kind in ("correct_sentence", "rewrite") and not e.text.strip():
        return False
    return True


def _norm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[\s]+", " ", s)
    s = s.strip(" .!?")
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return s


def grade_locally(exercise: Exercise, answer: str) -> Grade | None:
    """Deterministic grading where possible; None means 'ask the model'."""
    a = _norm(answer)
    if not a:
        return Grade(correct=False, score=0.0, feedback="You left it empty. The duck is unimpressed.", improved_answer=exercise.answer)
    if exercise.kind == "multiple_choice":
        correct = a == _norm(exercise.answer) or any(a == _norm(x) for x in exercise.accepted)
        return Grade(
            correct=correct,
            score=1.0 if correct else 0.0,
            feedback="Correct!" if correct else f"Not quite — the right choice was “{exercise.answer}”.",
            improved_answer=None if correct else exercise.answer,
        )
    if exercise.kind == "fill_gap":
        if a == _norm(exercise.answer) or any(a == _norm(x) for x in exercise.accepted):
            return Grade(correct=True, score=1.0, feedback="Exactly right.", improved_answer=None)
        return None  # let the model decide whether it's an acceptable alternative
    if exercise.kind == "correct_sentence" and a == _norm(exercise.answer):
        return Grade(correct=True, score=1.0, feedback="Spot on — that is exactly the fix.", improved_answer=None)
    return None


async def grade_answer(exercise: Exercise, answer: str, config: Config, pattern: Pattern | None) -> Grade:
    local = grade_locally(exercise, answer)
    if local is not None:
        return local
    model = build_model(config)
    agent = make_agent(model, Grade, P.GRADER, retries=1, fast=True)
    lines = [
        f"kind: {exercise.kind}",
        f"pattern: {pattern.title if pattern else exercise.pattern_key}",
        f"rule: {pattern.correct_form if pattern and pattern.correct_form else exercise.explanation}",
        f"prompt: {exercise.prompt}",
        f"text: {exercise.text}",
        f"reference answer: {exercise.answer}",
    ]
    if exercise.accepted:
        lines.append("accepted alternatives: " + " | ".join(exercise.accepted))
    lines.append(f"learner's answer: {answer.strip()}")
    result = await agent.run("\n".join(lines))
    grade: Grade = result.output
    grade.correct = grade.score >= 0.75
    return grade


def xp_for(grade: Grade) -> int:
    if grade.score >= 0.75:
        return XP_CORRECT
    if grade.score >= 0.4:
        return XP_PARTIAL
    return XP_WRONG


class SessionRunner:
    """Book-keeping for one practice session."""

    def __init__(self, store: Store, config: Config, exercises: list[Exercise]):
        self.store = store
        self.config = config
        self.exercises = exercises
        self.session_id = store.start_session(config.model, len(exercises))
        self.grades: list[Grade] = []
        self.xp = 0
        self.streak_before = compute_streak(store.session_dates())
        self.xp_before = store.total_xp()

    async def submit(self, index: int, answer: str) -> Grade:
        exercise = self.exercises[index]
        pattern = self.store.resolve_key(exercise.pattern_key)
        grade = await grade_answer(exercise, answer, self.config, pattern)
        self.grades.append(grade)
        self.xp += xp_for(grade)
        self.store.add_attempt(self.session_id, pattern.id if pattern else None, exercise, answer, grade)
        if pattern:
            self.store.record_practice(pattern.id, grade)
        return grade

    def finish(self) -> SessionSummary:
        total = len(self.exercises)
        correct = sum(1 for g in self.grades if g.score >= 0.75)
        partial = sum(1 for g in self.grades if 0.4 <= g.score < 0.75)
        score = (sum(g.score for g in self.grades) / total) if total else 0.0
        if total and correct == total:
            self.xp += XP_PERFECT_BONUS
        self.store.finish_session(self.session_id, correct=correct, partial=partial, score=score, xp=self.xp)
        xp_total = self.store.total_xp()
        streak = compute_streak(self.store.session_dates())
        level_before, _, _ = level_for(self.xp_before)
        level, title, _ = level_for(xp_total)
        self.store.clear_practice_cache()
        return SessionSummary(
            session_id=self.session_id,
            total=total,
            correct=correct,
            partial=partial,
            score=score,
            xp_earned=self.xp,
            xp_total=xp_total,
            streak=streak,
            streak_extended=streak > self.streak_before,
            level=level,
            level_title=title,
            leveled_up=level > level_before,
        )


ProgressLog = Callable[[str], None]
