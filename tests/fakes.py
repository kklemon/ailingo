"""A fake LLM layer so the whole app can be exercised without network access."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from ailingo.schemas import BatchAnalysis, Consolidation, ExerciseSet, Grade

ANALYSIS = {
    "findings": [
        {"prompt_index": 0, "pattern_key": "missing_article", "category": "grammar", "title": "Missing articles",
         "original": "add test for parser", "corrected": "add a test for the parser",
         "explanation": "Singular countable nouns need an article.", "one_off_typo": False},
        {"prompt_index": 0, "pattern_key": "german_word_order", "category": "grammar", "title": "German word order",
         "original": "has then a field", "corrected": "then has a field",
         "explanation": "Adverbs go before the verb in English.", "one_off_typo": False},
        {"prompt_index": 1, "pattern_key": "teh_typo", "category": "spelling", "title": "typo",
         "original": "teh", "corrected": "the", "explanation": "slip", "one_off_typo": True},
    ]
}

CONSOLIDATION = {
    "patterns": [
        {"key": "missing_article", "category": "grammar", "title": "Missing articles before nouns",
         "description": "You tend to drop 'a' and 'the' before singular nouns, especially in quick imperative prompts. German uses articles differently, so this is classic transfer.",
         "correct_form": "Singular countable nouns need an article: 'add test for parser' -> 'add a test for the parser'.",
         "tip": "If you can count it and it's singular, it needs an article.", "merged_keys": ["missing_article"]},
        {"key": "german_word_order", "category": "grammar", "title": "German word order in English",
         "description": "You sometimes put adverbs after the verb like in German ('has then'). English puts them before the main verb.",
         "correct_form": "'The user has then a field' -> 'The user then has a field'.",
         "tip": "Adverb first, then the verb.", "merged_keys": ["german_word_order"]},
    ]
}

EXERCISES = {
    "exercises": [
        {"kind": "multiple_choice", "pattern_key": "missing_article", "prompt": "Which version is correct?",
         "text": "", "options": ["Add migration for users table", "Add a migration for the users table", "Add the migration for users table"],
         "answer": "Add a migration for the users table", "accepted": [], "explanation": "Singular countable nouns need an article."},
        {"kind": "correct_sentence", "pattern_key": "german_word_order", "prompt": "Fix the mistake in this sentence.",
         "text": "The endpoint returns then a list of users.", "options": [],
         "answer": "The endpoint then returns a list of users.", "accepted": [], "explanation": "Adverbs go before the main verb."},
        {"kind": "fill_gap", "pattern_key": "missing_article", "prompt": "Fill the gap with the right article.",
         "text": "Please write ___ unit test for the parser.", "options": [], "answer": "a", "accepted": [],
         "explanation": "'Unit test' is singular and countable."},
    ]
}

GRADE = {"correct": False, "score": 0.5, "feedback": "The word order is fixed, but you dropped the article.",
         "improved_answer": "The endpoint then returns a list of users."}


def fake_make_agent(model: Any, output_type: type, instructions: str, retries: int = 2, *, fast: bool = False) -> Agent:
    outputs = {BatchAnalysis: ANALYSIS, Consolidation: CONSOLIDATION, ExerciseSet: EXERCISES, Grade: GRADE}
    return Agent(TestModel(custom_output_args=outputs[output_type]), output_type=output_type)


def fake_build_model(config: Any, model_id: str | None = None) -> TestModel:
    return TestModel()


async def fake_test_connection(config: Any, model_id: str | None = None) -> str:
    return "Quack ready"


def install(monkeypatch) -> None:
    import ailingo.analysis as analysis
    import ailingo.practice as practice
    import ailingo.tui.screens.onboarding as onboarding
    import ailingo.tui.screens.settings as settings

    monkeypatch.setattr(analysis, "build_model", fake_build_model)
    monkeypatch.setattr(analysis, "make_agent", fake_make_agent)
    monkeypatch.setattr(practice, "build_model", fake_build_model)
    monkeypatch.setattr(practice, "make_agent", fake_make_agent)
    monkeypatch.setattr(onboarding, "test_connection", fake_test_connection)
    monkeypatch.setattr(settings, "test_connection", fake_test_connection)
