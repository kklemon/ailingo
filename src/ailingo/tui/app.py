"""The Textual application."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.theme import Theme

from ..config import Config, save_config
from ..store import Store

DUCKPOND = Theme(
    name="duckpond",
    primary="#F2B705",
    secondary="#4CC9F0",
    accent="#FF6B35",
    warning="#FFB703",
    error="#E63946",
    success="#2A9D8F",
    background="#14161B",
    surface="#1E222A",
    panel="#262B35",
    dark=True,
)


class AilingoApp(App[None]):
    TITLE = "ailingo"
    SUB_TITLE = "your prompts, judged by a duck"
    CSS_PATH = "styles.tcss"
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", priority=True)]

    def __init__(self, config: Config, store: Store) -> None:
        super().__init__()
        self.config = config
        self.store = store

    def on_mount(self) -> None:
        self.register_theme(DUCKPOND)
        self.theme = "duckpond"
        from .screens.home import HomeScreen
        from .screens.onboarding import OnboardingScreen

        self.push_screen(HomeScreen())
        if not self.config.onboarded or not self.config.model:
            self.push_screen(OnboardingScreen())

    def save_config(self) -> None:
        save_config(self.config)

    def new_store(self) -> Store:
        """A fresh connection for use from thread workers."""
        return Store(self.store.path)
