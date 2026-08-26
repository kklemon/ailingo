from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import LoadingIndicator, Static

from ...gamification import say
from ..widgets import Mascot


class LoadingScreen(ModalScreen[None]):
    def __init__(self, context: str = "loading_exercises", title: str = "One moment") -> None:
        super().__init__()
        self._quip_context = context
        self._heading = title

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-box"):
            yield Static(self._heading, classes="title")
            yield Mascot("thinking", say(self._quip_context))
            yield LoadingIndicator()

    def set_line(self, line: str) -> None:
        self.query_one(Mascot).set(line=line)
