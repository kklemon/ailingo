from __future__ import annotations

from datetime import UTC, datetime

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, ProgressBar, Sparkline, Static

from ...analysis import analysis_is_due, analyze_pending
from ...gamification import compute_streak, greeting, level_for, practiced_today, say
from ...ingest import ingest_all
from ...llm.client import humanize_error
from ...practice import SessionRunner, generate_session
from ..widgets import Mascot, StatCard
from .loading import LoadingScreen


class HomeScreen(Screen):
    BINDINGS = [
        Binding("s", "start_session", "Practice"),
        Binding("w", "patterns", "Weak spots"),
        Binding("y", "sync", "Sync & analyze"),
        Binding("comma", "settings", "Settings"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="home"):
            yield Static("ailingo", classes="title")
            yield Static("Your personal English coach, trained on your own prompts.", classes="subtitle")
            yield Mascot("happy", "", id="home-mascot")
            with Horizontal(id="home-stats"):
                yield StatCard("Streak", "0", "days", id="stat-streak")
                yield StatCard("XP", "0", "", id="stat-xp")
                yield StatCard("Weak spots", "0", "patterns", id="stat-patterns")
                yield StatCard("Sessions", "0", "completed", id="stat-sessions")
            with Vertical(id="home-level"):
                yield Static("", id="home-level-label")
                yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="home-level-bar")
            yield Sparkline([], id="home-spark")
            yield Static("", id="home-status")
            with Horizontal(id="home-actions"):
                yield Button("Practice now", id="btn-session", variant="primary")
                yield Button("Weak spots", id="btn-patterns")
                yield Button("Sync & analyze", id="btn-sync")
                yield Button("Settings", id="btn-settings")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_stats()
        if self.app.config.onboarded and self.app.config.model:
            self.background_sync()

    def on_screen_resume(self) -> None:
        self.refresh_stats()

    # ---------------------------------------------------------------- data --

    def refresh_stats(self) -> None:
        store = self.app.store
        cfg = self.app.config
        days = store.session_dates()
        streak = compute_streak(days)
        xp = store.total_xp()
        level, title, next_xp = level_for(xp)
        patterns = store.patterns()
        sessions = store.sessions_completed()

        self.query_one("#stat-streak", StatCard).set(str(streak), "day" if streak == 1 else "days")
        self.query_one("#stat-xp", StatCard).set(str(xp), f"level {level}")
        self.query_one("#stat-patterns", StatCard).set(str(len(patterns)), "patterns")
        self.query_one("#stat-sessions", StatCard).set(str(sessions), "completed")

        bar = self.query_one("#home-level-bar", ProgressBar)
        if next_xp is None:
            self.query_one("#home-level-label", Static).update(f"Level {level} · {title} · max level reached")
            bar.update(total=1, progress=1)
        else:
            prev = max(t for t, _ in _thresholds() if t <= xp)
            span = max(next_xp - prev, 1)
            self.query_one("#home-level-label", Static).update(
                f"Level {level} · {title} · {xp - prev}/{span} XP to level {level + 1}"
            )
            bar.update(total=span, progress=xp - prev)

        scores = store.recent_scores()
        spark = self.query_one("#home-spark", Sparkline)
        spark.data = [round(s * 100) for s in scores] if len(scores) >= 2 else []
        spark.display = len(scores) >= 2

        mascot = self.query_one("#home-mascot", Mascot)
        name = f"{cfg.user_name}. " if cfg.user_name else ""
        if not patterns:
            mascot.set("sleepy", name + say("no_patterns"))
        elif practiced_today(days):
            mascot.set("proud", name + say("practiced_today"))
        elif streak > 0:
            mascot.set("happy", name + say("streak_kept") + " " + greeting())
        elif sessions > 0:
            mascot.set("sad", name + say("streak_lost"))
        else:
            mascot.set("happy", name + greeting())
        self.query_one("#btn-session", Button).disabled = not patterns
        self.update_status()

    def update_status(self, extra: str | None = None) -> None:
        store = self.app.store
        parts: list[str] = []
        last = store.get_dt("last_analysis_at")
        if last:
            age = datetime.now(UTC) - last
            parts.append(f"last analysis {_ago(age)}")
        pending = store.pending_count()
        if pending:
            parts.append(f"{pending} prompts waiting")
        if extra:
            parts.append(extra)
        elif last and analysis_is_due(store, self.app.config):
            parts.append("analysis due — press y")
        self.query_one("#home-status", Static).update(" · ".join(parts))

    # ------------------------------------------------------------- actions --

    def action_start_session(self) -> None:
        if not self.app.store.patterns():
            self.notify("No weak spots yet — run a sync first.", severity="warning")
            return
        self.start_session()

    def action_patterns(self) -> None:
        from .patterns import PatternsScreen

        self.app.push_screen(PatternsScreen())

    def action_sync(self) -> None:
        from .sync import SyncScreen

        self.app.push_screen(SyncScreen())

    def action_settings(self) -> None:
        from .settings import SettingsScreen

        self.app.push_screen(SettingsScreen())

    @on(Button.Pressed, "#btn-session")
    def _btn_session(self) -> None:
        self.action_start_session()

    @on(Button.Pressed, "#btn-patterns")
    def _btn_patterns(self) -> None:
        self.action_patterns()

    @on(Button.Pressed, "#btn-sync")
    def _btn_sync(self) -> None:
        self.action_sync()

    @on(Button.Pressed, "#btn-settings")
    def _btn_settings(self) -> None:
        self.action_settings()

    # ------------------------------------------------------------- workers --

    @work(exclusive=True, group="session", exit_on_error=False)
    async def start_session(self) -> None:
        from .session import SessionScreen

        store, cfg = self.app.store, self.app.config
        exercises = store.cached_session()
        loading: LoadingScreen | None = None
        if not exercises:
            loading = LoadingScreen("loading_exercises", "Preparing your session")
            self.app.push_screen(loading)
            try:
                exercises = await generate_session(store, cfg)
            except Exception as exc:
                self.app.pop_screen()
                self.notify(humanize_error(exc), severity="error", timeout=10)
                return
        else:
            store.clear_practice_cache()
        if loading is not None:
            self.app.pop_screen()
        runner = SessionRunner(store, cfg, exercises)
        self.app.push_screen(SessionScreen(runner))

    @work(thread=True, exclusive=True, group="sync", exit_on_error=False)
    def background_sync(self) -> None:
        """Ingest quietly on startup; run the weekly analysis if it is due."""
        store = self.app.new_store()
        try:
            ingest_all(store, self.app.config)
            due = analysis_is_due(store, self.app.config)
        finally:
            store.close()
        self.app.call_from_thread(self.refresh_stats)
        if due and self.app.config.auto_analyze:
            self.app.call_from_thread(self.background_analysis)

    @work(exclusive=True, group="analysis", exit_on_error=False)
    async def background_analysis(self) -> None:
        store, cfg = self.app.store, self.app.config
        pending = store.pending_count()
        self.update_status(f"Quill is reading {min(pending, cfg.max_prompts_per_run)} new prompts…")
        try:
            report = await analyze_pending(store, cfg)
        except Exception as exc:
            self.update_status(f"analysis failed: {humanize_error(exc)}")
            return
        self.notify(
            f"Analysis done: {report.findings} findings, {report.new_patterns} new patterns.",
            title="Quill has opinions",
        )
        self.refresh_stats()


def _thresholds() -> list[tuple[int, str]]:
    from ...gamification import LEVELS

    return LEVELS


def _ago(delta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 3600:
        return "just now" if seconds < 120 else f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    return "yesterday" if days == 1 else f"{days} days ago"
