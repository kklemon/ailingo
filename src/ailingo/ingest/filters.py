"""Heuristics that turn raw agent transcripts into analyzable human prompts."""

from __future__ import annotations

import re

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]{1,200}`")
SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
LEADING_TAG_RE = re.compile(r"^\s*<([a-zA-Z][a-zA-Z0-9_-]*)[\s>]")
XML_BLOCK_RE = re.compile(r"<(environment_context|user_instructions|task-notification|command-name|"
                          r"local-command-stdout|command-message|ide_opened_file|ide_selection|bash-input|"
                          r"bash-stdout|bash-stderr)>.*?</\1>", re.DOTALL)
URL_RE = re.compile(r"https?://\S+")
PATH_RE = re.compile(r"(?<![\w/])(?:~|\.{1,2})?/(?:[\w.@-]+/)+[\w.@-]*")
PASTE_RE = re.compile(r"\[Pasted text #\d+[^\]]*\]")
IMAGE_RE = re.compile(r"\[Image #\d+\]")

SKIP_PREFIXES = (
    "[Request interrupted",
    "This session is being continued from a previous conversation",
    "Caveat: The messages below were generated",
    "Implement the following plan:",
    "Base directory for this skill",
)

MAX_CHARS = 1400

# tiny stop-word lists for a cheap English/German language guess
_EN = {
    "the", "and", "to", "of", "a", "in", "is", "it", "that", "for", "with", "on", "this", "be", "are",
    "should", "when", "not", "we", "you", "can", "from", "an", "as", "at", "by", "or", "if", "but",
    "please", "add", "make", "use", "fix", "change", "also", "so", "then", "there", "which", "into",
    "all", "only", "does", "do", "have", "has", "will", "would", "now", "new", "like", "same",
}
_DE = {
    "und", "der", "die", "das", "nicht", "ist", "ich", "wir", "mit", "für", "auf", "ein", "eine",
    "einen", "sollte", "sollten", "möchte", "bitte", "auch", "wird", "werden", "sind", "dass", "noch",
    "aber", "wenn", "oder", "bei", "nach", "über", "zum", "zur", "kann", "können", "diese", "dieser",
    "dieses", "wie", "was", "es", "sich", "im", "am", "vom", "dem", "den", "des", "als", "nur", "muss",
    "müssen", "soll", "sollen", "hier", "jetzt", "dann", "mehr", "sehr", "gibt", "haben", "hat",
}
_WORD_RE = re.compile(r"[a-zA-ZäöüßÄÖÜ']+")


def clean_text(text: str) -> str:
    """Strip everything that is not the human's own English prose."""
    text = SYSTEM_REMINDER_RE.sub(" ", text)
    text = XML_BLOCK_RE.sub(" ", text)
    text = FENCE_RE.sub(" [code] ", text)
    text = INLINE_CODE_RE.sub(" [code] ", text)
    text = URL_RE.sub(" [url] ", text)
    text = PASTE_RE.sub(" [pasted] ", text)
    text = IMAGE_RE.sub(" [image] ", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    # drop lines that look like logs / tracebacks / diffs / pure paths
    kept: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            kept.append("")
            continue
        if re.match(r"^(Traceback|File \"|at [\w.$]+\(|\s*\^+$|[+-]{3} |@@ |\$ |>>> |ERROR|WARN|INFO|DEBUG|\d{4}-\d{2}-\d{2}[T ]\d{2}:)", s):
            continue
        if len(s) > 40 and sum(c.isalpha() or c.isspace() for c in s) / len(s) < 0.6:
            continue  # mostly symbols / data
        kept.append(s)
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        # cut at a sentence boundary if there is one reasonably late
        m = max(cut.rfind(". "), cut.rfind("\n"))
        if m > MAX_CHARS * 0.6:
            cut = cut[: m + 1]
        text = cut.rstrip() + " …"
    return text


def is_human_prompt(raw: str) -> bool:
    if not raw:
        return False
    s = raw.strip()
    if not s:
        return False
    if s.startswith("/") and "\n" not in s and len(s) < 80:
        return False  # slash command
    if any(s.startswith(p) for p in SKIP_PREFIXES):
        return False
    stripped = SYSTEM_REMINDER_RE.sub("", s).strip()
    if not stripped:
        return False
    if LEADING_TAG_RE.match(stripped):
        return False
    return True


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def detect_language(text: str) -> str:
    """Return 'en', 'de' or 'other'. Deliberately biased towards 'en' for short texts."""
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return "other"
    en = sum(1 for w in words if w in _EN)
    de = sum(1 for w in words if w in _DE)
    if de >= 2 and de > en:
        return "de"
    if en == 0 and de == 0 and len(words) >= 12:
        # long text without a single english function word: probably not english
        ascii_ratio = sum(1 for w in words if w.isascii()) / len(words)
        if ascii_ratio < 0.9:
            return "other"
    return "en"


def prepare(raw: str) -> tuple[str, str] | None:
    """Return (clean_text, language) or None when the text is not worth analyzing."""
    if not is_human_prompt(raw):
        return None
    text = clean_text(raw)
    if word_count(text.replace("[code]", "").replace("[url]", "")) < 3:
        return None
    return text, detect_language(text)
