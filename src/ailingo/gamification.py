"""Streaks, XP levels and Quill — the rubber duck who has read all your prompts."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

LEVELS: list[tuple[int, str]] = [
    (0, "Typo Goblin"),
    (40, "Comma Apprentice"),
    (120, "Article Adder"),
    (250, "Preposition Wrangler"),
    (420, "Tense Tamer"),
    (650, "Syntax Sorcerer"),
    (950, "Idiom Insider"),
    (1350, "Prompt Poet"),
    (1900, "Duck Whisperer"),
    (2600, "Grammar Deity"),
]


def level_for(xp: int) -> tuple[int, str, int | None]:
    """Return (level number, title, xp needed for next level or None at max)."""
    level = 1
    title = LEVELS[0][1]
    next_threshold: int | None = None
    for i, (threshold, name) in enumerate(LEVELS):
        if xp >= threshold:
            level, title = i + 1, name
            next_threshold = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
    return level, title, next_threshold


def compute_streak(days: set[date], today: date | None = None) -> int:
    """Consecutive practice days ending today or yesterday."""
    today = today or date.today()
    if not days:
        return 0
    cursor = today if today in days else today - timedelta(days=1)
    if cursor not in days:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def practiced_today(days: set[date], today: date | None = None) -> bool:
    return (today or date.today()) in days


# ------------------------------------------------------------------ mascot --

DUCK = {
    "happy": r"""
   __
 <(o )___
  ( ._> /
   `---'
""",
    "proud": r"""
   __
 <(^ )___
  ( ._> /
   `---'
""",
    "thinking": r"""
   __  ?
 <(- )___
  ( ._> /
   `---'
""",
    "sad": r"""
   __
 <(o )___
  ( .-> /
   `---'
""",
    "sleepy": r"""
   __  z
 <(- )___
  ( ._> /
   `---'
""",
    "shocked": r"""
   __  !
 <(O )___
  ( ._> /
   `---'
""",
}

LINES: dict[str, list[str]] = {
    "greet_morning": [
        "Morning. Coffee first, articles second.",
        "Early bird catches the missing preposition.",
        "Good morning. Your prompts kept me up all night.",
    ],
    "greet_afternoon": [
        "Afternoon. Let's fix a few sentences before the next deploy.",
        "Back already? Your Codex thanks you in advance.",
        "Lunch is over. Time to feed the duck some grammar.",
    ],
    "greet_evening": [
        "Evening. One short session and you can go back to breaking prod.",
        "Good evening. I read 300 of your prompts today. I need this more than you.",
        "Let's end the day with fewer commas in the wrong places.",
    ],
    "greet_night": [
        "It's late. Just a few minutes, then sleep — you type worse when tired.",
        "Night owl mode. The duck approves, grudgingly.",
    ],
    "no_patterns": [
        "I have not read your prompts yet. Sync, and I'll judge you gently.",
        "No data, no judgement. Run a sync so I have something to work with.",
    ],
    "practiced_today": [
        "You already practised today. I'm... proud? Is this what pride feels like?",
        "Done for today. Go write a prompt without a comma splice. I dare you.",
    ],
    "streak_kept": [
        "Streak intact. The duck nods approvingly.",
        "Consistency! Unlike your use of articles.",
    ],
    "streak_lost": [
        "Your streak died. It went peacefully. Let's start a new one.",
        "The streak is gone, but the mistakes remain. Convenient, isn't it?",
    ],
    "loading_exercises": [
        "Writing exercises based on your finest mistakes…",
        "Consulting my notes. Oh, there are so many notes…",
        "Brewing questions. This may sting a little.",
        "Picking your weak spots. It was hard to choose.",
    ],
    "loading_analysis": [
        "Reading your prompts. Oh. Oh no.",
        "Digesting your prose. Chewing slowly.",
        "Scanning for crimes against the article.",
    ],
    "grading": [
        "Hmm, let me think…",
        "Judging. Silently. For now.",
        "Reading your answer twice, just to be fair.",
    ],
    "correct": [
        "Correct! I'll update my low expectations.",
        "Yes! That's the one. Quack.",
        "Nailed it. Your prompts will be so much fancier.",
        "Right. I'm going to pretend that wasn't a lucky guess.",
        "Flawless. Someone has been paying attention.",
    ],
    "partial": [
        "Close. Half a quack.",
        "Almost. The main thing is fixed, but there's a crumb left.",
        "Nearly there — check the details.",
    ],
    "wrong": [
        "Nope. But wrong on purpose is how we learn, right? Right?",
        "Not this time. Read the explanation and I'll forget this happened.",
        "That's the exact mistake from your prompts. Consistent, at least.",
        "Wrong, but confidently. I respect that.",
    ],
    "session_perfect": [
        "Perfect session! I have nothing to complain about. This is unsettling.",
        "100%! Are you sure you need me? ...Yes. Yes you do.",
    ],
    "session_good": [
        "Solid work. Your future prompts are already grateful.",
        "Good session. A few slips, but you're clearly getting it.",
    ],
    "session_meh": [
        "That was rough, but you showed up. Showing up is 80% of the duck.",
        "Well. Now we both know what to practise tomorrow.",
    ],
    "level_up": [
        "LEVEL UP! New title acquired. Your business cards are now obsolete.",
        "You leveled up! I'd throw confetti but I have no arms.",
    ],
}


def say(context: str, rng: random.Random | None = None) -> str:
    rng = rng or random
    options = LINES.get(context) or ["Quack."]
    return rng.choice(options)


def greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if 5 <= hour < 12:
        return say("greet_morning")
    if 12 <= hour < 18:
        return say("greet_afternoon")
    if 18 <= hour < 23:
        return say("greet_evening")
    return say("greet_night")


def reaction_for_score(score: float) -> tuple[str, str]:
    """Return (mood, line) for an answer grade."""
    if score >= 0.75:
        return "proud", say("correct")
    if score >= 0.4:
        return "thinking", say("partial")
    return "sad", say("wrong")


def session_verdict(score: float) -> tuple[str, str]:
    if score >= 0.999:
        return "proud", say("session_perfect")
    if score >= 0.6:
        return "happy", say("session_good")
    return "sad", say("session_meh")
