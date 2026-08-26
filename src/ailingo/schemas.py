"""Pydantic models shared between the LLM layer, the store and the TUI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["grammar", "word_usage", "spelling", "punctuation", "phrasing"]
CATEGORY_LABELS: dict[str, str] = {
    "grammar": "Grammar",
    "word_usage": "Word usage",
    "spelling": "Spelling",
    "punctuation": "Punctuation",
    "phrasing": "Phrasing",
}

ExerciseKind = Literal["correct_sentence", "fill_gap", "multiple_choice", "rewrite"]
KIND_LABELS: dict[str, str] = {
    "correct_sentence": "Fix the sentence",
    "fill_gap": "Fill the gap",
    "multiple_choice": "Pick the right one",
    "rewrite": "Make it natural",
}


# ---------------------------------------------------------------- analysis --


class Finding(BaseModel):
    """One mistake spotted in one prompt."""

    prompt_index: int = Field(description="Index of the prompt in the batch, as given in the [n] marker.")
    pattern_key: str = Field(
        description=(
            "Short snake_case key naming the KIND of mistake (e.g. missing_article, "
            "wrong_preposition, comma_splice, which_vs_that). Reuse an existing key when "
            "the mistake is the same kind."
        )
    )
    category: Category
    title: str = Field(description="Short human-readable name of the mistake kind, max 8 words.")
    original: str = Field(description="Shortest verbatim excerpt from the prompt containing the mistake.")
    corrected: str = Field(description="The same excerpt with only the mistake fixed.")
    explanation: str = Field(description="One or two sentences explaining the rule.")
    one_off_typo: bool = Field(
        description=(
            "True if this is clearly a slip of the fingers (transposed, missing or doubled "
            "letters, wrong neighbouring key, missing space) rather than a language habit."
        )
    )


class BatchAnalysis(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class PatternSpec(BaseModel):
    """A consolidated mistake pattern as written by the consolidator agent."""

    key: str = Field(description="Canonical snake_case key. Must be one of merged_keys.")
    category: Category
    title: str = Field(description="Max 8 words.")
    description: str = Field(description="2-3 sentences, second person: what the writer tends to do and when.")
    correct_form: str = Field(description="The rule, with a minimal 'wrong -> right' example.")
    tip: str = Field(description="One memorable sentence to remember the rule.")
    merged_keys: list[str] = Field(description="All input keys this pattern absorbs, including its own key.")


class Consolidation(BaseModel):
    patterns: list[PatternSpec]


# ---------------------------------------------------------------- practice --


class Exercise(BaseModel):
    kind: ExerciseKind
    pattern_key: str
    prompt: str = Field(description="The instruction or question shown to the learner.")
    text: str = Field(default="", description="The sentence to fix / with a ___ gap / to rewrite. May be empty for multiple_choice.")
    options: list[str] = Field(default_factory=list, description="multiple_choice only: 3-4 options, exactly one correct.")
    answer: str = Field(description="Reference correct answer. For multiple_choice it must equal one option verbatim.")
    accepted: list[str] = Field(default_factory=list, description="Other acceptable answers (fill_gap / multiple_choice).")
    explanation: str = Field(description="Shown after answering. Max 2 sentences stating the rule.")


class ExerciseSet(BaseModel):
    exercises: list[Exercise]


class Grade(BaseModel):
    correct: bool
    score: float = Field(ge=0.0, le=1.0)
    feedback: str = Field(description="Max 2 friendly, specific sentences addressed to the learner.")
    improved_answer: str | None = Field(default=None, description="Best version of the answer if the learner's was not perfect.")


# ------------------------------------------------------------------- store --


class Pattern(BaseModel):
    id: int
    key: str
    category: str
    title: str
    description: str
    correct_form: str
    tip: str
    evidence_count: int
    mastery: float
    first_seen: datetime | None
    last_seen: datetime | None
    last_practiced: datetime | None
    times_practiced: int
    times_correct: int
    archived: bool

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category.title())


class Example(BaseModel):
    id: int
    pattern_id: int
    original: str
    corrected: str
    note: str
    created_at: datetime | None


class SessionSummary(BaseModel):
    session_id: int
    total: int
    correct: int
    partial: int
    score: float
    xp_earned: int
    xp_total: int
    streak: int
    streak_extended: bool
    level: int
    level_title: str
    leveled_up: bool
