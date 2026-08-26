"""Reusable widgets: the mascot and stat cards."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Digits, Label, Static

from ..gamification import DUCK


class Mascot(Horizontal):
    """Quill the duck plus a speech bubble."""

    DEFAULT_CSS = """
    Mascot {
        height: auto;
        width: 100%;
        padding: 0 1;
    }
    Mascot > .mascot--art {
        width: 12;
        height: auto;
        color: $primary;
        text-style: bold;
    }
    Mascot > .mascot--bubble {
        width: 1fr;
        height: auto;
        border: round $primary 60%;
        padding: 0 1;
        margin: 0 0 0 1;
        color: $foreground;
    }
    """

    def __init__(self, mood: str = "happy", line: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._duck_mood = mood
        self._duck_line = line

    def compose(self) -> ComposeResult:
        yield Static(DUCK.get(self._duck_mood, DUCK["happy"]).strip("\n"), classes="mascot--art", id="mascot-art")
        yield Static(self._duck_line, classes="mascot--bubble", id="mascot-bubble")

    def set(self, mood: str | None = None, line: str | None = None) -> None:
        if mood is not None:
            self._duck_mood = mood
            self.query_one("#mascot-art", Static).update(DUCK.get(self._duck_mood, DUCK["happy"]).strip("\n"))
        if line is not None:
            self._duck_line = line
            self.query_one("#mascot-bubble", Static).update(self._duck_line)


class StatCard(Vertical):
    DEFAULT_CSS = """
    StatCard {
        width: 1fr;
        height: auto;
        border: round $panel-lighten-2;
        padding: 0 1;
        margin: 0 1 0 0;
        align: center middle;
    }
    StatCard > Label { color: $text-muted; text-align: center; width: 100%; }
    StatCard > Digits { width: 100%; text-align: center; color: $primary; }
    StatCard > .stat--sub { color: $text-muted; text-align: center; width: 100%; }
    """

    def __init__(self, title: str, value: str, sub: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._card_title, self._card_value, self._card_sub = title, value, sub

    def compose(self) -> ComposeResult:
        yield Label(self._card_title)
        yield Digits(self._card_value, id="stat-value")
        yield Static(self._card_sub, classes="stat--sub", id="stat-sub")

    def set(self, value: str, sub: str | None = None) -> None:
        self.query_one("#stat-value", Digits).update(value)
        if sub is not None:
            self.query_one("#stat-sub", Static).update(sub)
