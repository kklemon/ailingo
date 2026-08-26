from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, ProgressBar, RichLog, Static

from ...analysis import analyze_pending
from ...gamification import say
from ...ingest import ingest_all
from ...llm.client import humanize_error
from ..widgets import Mascot


class SyncScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, analyze: bool = True, max_prompts: int | None = None) -> None:
        super().__init__()
        self._do_analyze = analyze
        self._max_prompts = max_prompts
        self._working = False

    def compose(self) -> ComposeResult:
        with Vertical(id="sync"):
            yield Static("Sync & analyze", classes="title")
            yield Mascot("thinking", say("loading_analysis"), id="sync-mascot")
            yield ProgressBar(total=1, show_eta=False, id="sync-progress")
            yield RichLog(id="sync-log", wrap=True, markup=False)
            with Horizontal(id="sync-actions"):
                yield Button("Back", id="btn-back", variant="primary", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_sync()

    def log_line(self, text: str) -> None:
        self.query_one("#sync-log", RichLog).write(text)

    def set_progress(self, done: int, total: int) -> None:
        self.query_one("#sync-progress", ProgressBar).update(total=max(total, 1), progress=done)

    @work(exclusive=True, group="sync", exit_on_error=False)
    async def run_sync(self) -> None:
        self._working = True
        cfg = self.app.config
        store = self.app.store
        self.log_line("Reading transcripts …")
        import asyncio

        def _ingest() -> None:
            local = self.app.new_store()
            try:
                ingest_all(local, cfg, lambda m: self.app.call_from_thread(self.log_line, m))
            finally:
                local.close()

        await asyncio.to_thread(_ingest)
        pending = store.pending_count()
        self.log_line(f"{pending} prompts waiting for analysis.")
        if self._do_analyze and pending:
            limit = self._max_prompts if self._max_prompts is not None else cfg.max_prompts_per_run
            if pending > limit:
                self.log_line(f"Analyzing the {limit} most recent now; the rest next time.")
            try:
                report = await analyze_pending(
                    store, cfg, self.log_line, max_prompts=limit, progress=self.set_progress
                )
            except Exception as exc:
                self.log_line(f"Analysis failed: {humanize_error(exc)}")
                self.query_one("#sync-mascot", Mascot).set("shocked", "That did not go well. Check Settings.")
            else:
                mood = "proud" if report.findings else "happy"
                self.query_one("#sync-mascot", Mascot).set(
                    mood,
                    f"I found {report.findings} things to talk about across {report.prompts_analyzed} prompts. "
                    f"{len(store.patterns())} weak spots on file."
                    if report.findings
                    else "Nothing new to pick on. Suspicious.",
                )
        else:
            self.set_progress(1, 1)
            self.query_one("#sync-mascot", Mascot).set("happy", "Transcripts synced.")
        self._working = False
        btn = self.query_one("#btn-back", Button)
        btn.disabled = False
        btn.focus()

    def action_back(self) -> None:
        if self._working:
            self.notify("Still working — let it finish (or Ctrl+Q to quit).", severity="warning")
            return
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-back")
    def _back(self) -> None:
        self.action_back()
