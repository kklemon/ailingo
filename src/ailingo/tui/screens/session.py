from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option

from ...gamification import reaction_for_score, say, session_verdict
from ...llm.client import humanize_error
from ...practice import SessionRunner, generate_session
from ...schemas import KIND_LABELS, Exercise, Grade, SessionSummary
from ..widgets import Mascot, StatCard


class SessionScreen(Screen):
    BINDINGS = [Binding("escape", "abandon", "Abandon session")]

    def __init__(self, runner: SessionRunner) -> None:
        super().__init__()
        self.runner = runner
        self.index = 0
        self._grading = False
        self._mc_options: dict[str, str] = {}

    @property
    def exercises(self) -> list[Exercise]:
        return self.runner.exercises

    def compose(self) -> ComposeResult:
        with Vertical(id="session"):
            yield Static("", id="session-title", classes="title")
            yield ProgressBar(total=len(self.exercises), show_eta=False, id="session-progress")
            yield Mascot("happy", say("loading_exercises"), id="session-mascot")
            with Vertical(id="card"):
                yield Static("", id="card-kind")
                yield Static("", id="card-prompt")
                yield Static("", id="card-text")
                yield Container(id="answer-area")
                yield Static("", id="answer-hint")
            with Vertical(id="feedback", classes="hidden"):
                yield Static("", id="feedback-verdict")
                yield Static("", id="feedback-text")
                yield Static("", id="feedback-improved")
                yield Static("", id="feedback-explanation")
                with Horizontal(id="feedback-actions"):
                    yield Button("Next", id="btn-next", variant="primary")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#session-mascot", Mascot).set("happy", "Let's go. Read carefully, answer, press Enter.")
        await self.show_exercise()

    # ------------------------------------------------------------ display --

    async def show_exercise(self) -> None:
        ex = self.exercises[self.index]
        pattern = self.app.store.resolve_key(ex.pattern_key)
        n, total = self.index + 1, len(self.exercises)
        self.query_one("#session-title", Static).update(f"Exercise {n} of {total}")
        self.query_one("#session-progress", ProgressBar).update(progress=self.index)
        kind = KIND_LABELS.get(ex.kind, ex.kind)
        topic = f" · {pattern.title}" if pattern else ""
        self.query_one("#card-kind", Static).update(f"{kind}{topic}")
        self.query_one("#card-prompt", Static).update(ex.prompt)
        text_widget = self.query_one("#card-text", Static)
        text_widget.update(ex.text)
        text_widget.display = bool(ex.text.strip())
        self.query_one("#feedback").add_class("hidden")
        self.query_one("#feedback").remove_class("correct", "partial", "wrong")

        area = self.query_one("#answer-area", Container)
        await area.remove_children()
        hint = self.query_one("#answer-hint", Static)
        self._mc_options = {}
        if ex.kind == "multiple_choice":
            options = [Option(opt, id=f"opt{i}") for i, opt in enumerate(ex.options)]
            self._mc_options = {f"opt{i}": opt for i, opt in enumerate(ex.options)}
            widget = OptionList(*options, id="answer-options")
            await area.mount(widget)
            widget.focus()
            hint.update("↑/↓ to choose, Enter to answer.")
        else:
            if ex.kind == "fill_gap":
                inp = Input(placeholder="the missing word(s)", id="answer-input")
                hint.update("Type only what goes into the gap, then Enter.")
            elif ex.kind == "correct_sentence":
                inp = Input(value=ex.text, id="answer-input")
                hint.update("Edit the sentence in place, then Enter.")
            else:
                inp = Input(value=ex.text, id="answer-input")
                hint.update("Rewrite it so it sounds natural, then Enter.")
            await area.mount(inp)
            inp.focus()
            if ex.kind != "fill_gap":
                inp.cursor_position = len(inp.value)

    # ------------------------------------------------------------ answers --

    @on(Input.Submitted, "#answer-input")
    def _input_submitted(self, event: Input.Submitted) -> None:
        self.submit(event.value)

    @on(OptionList.OptionSelected, "#answer-options")
    def _option_selected(self, event: OptionList.OptionSelected) -> None:
        answer = self._mc_options.get(str(event.option.id), str(event.option.prompt))
        self.submit(answer)

    @work(exclusive=True, group="grade", exit_on_error=False)
    async def submit(self, answer: str) -> None:
        if self._grading:
            return
        self._grading = True
        area = self.query_one("#answer-area", Container)
        for child in area.children:
            child.disabled = True
        mascot = self.query_one("#session-mascot", Mascot)
        mascot.set("thinking", say("grading"))
        try:
            grade = await self.runner.submit(self.index, answer)
        except Exception as exc:
            self._grading = False
            for child in area.children:
                child.disabled = False
            mascot.set("shocked", "Grading failed. Try again.")
            self.notify(humanize_error(exc), severity="error", timeout=10)
            return
        self.show_feedback(grade)
        self._grading = False

    def show_feedback(self, grade: Grade) -> None:
        ex = self.exercises[self.index]
        mood, line = reaction_for_score(grade.score)
        self.query_one("#session-mascot", Mascot).set(mood, line)
        box = self.query_one("#feedback")
        box.remove_class("hidden")
        if grade.score >= 0.75:
            box.add_class("correct")
            verdict = "✔ Correct"
        elif grade.score >= 0.4:
            box.add_class("partial")
            verdict = "◐ Partly right"
        else:
            box.add_class("wrong")
            verdict = "✘ Not quite"
        self.query_one("#feedback-verdict", Static).update(verdict)
        self.query_one("#feedback-text", Static).update(grade.feedback)
        improved = self.query_one("#feedback-improved", Static)
        if grade.improved_answer and grade.score < 1.0:
            improved.update(f"Better: {grade.improved_answer}")
            improved.display = True
        else:
            improved.display = False
        self.query_one("#feedback-explanation", Static).update(f"Rule: {ex.explanation}")
        last = self.index + 1 >= len(self.exercises)
        btn = self.query_one("#btn-next", Button)
        btn.label = "Finish" if last else "Next"
        btn.focus()

    @on(Button.Pressed, "#btn-next")
    async def _next(self) -> None:
        self.index += 1
        if self.index >= len(self.exercises):
            self.finish()
            return
        await self.show_exercise()

    def finish(self) -> None:
        summary = self.runner.finish()
        self.app.pop_screen()
        self.app.push_screen(SummaryScreen(summary))

    def action_abandon(self) -> None:
        if self.runner.grades:
            self.runner.finish()
        self.app.pop_screen()


class SummaryScreen(Screen):
    BINDINGS = [Binding("escape", "home", "Home"), Binding("enter", "home", "Home", show=False)]

    def __init__(self, summary: SessionSummary) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        s = self.summary
        mood, line = session_verdict(s.score)
        if s.leveled_up:
            mood, line = "proud", say("level_up") + f" You are now a {s.level_title}."
        with Vertical(id="summary"):
            yield Static("Session complete", classes="title")
            yield Mascot(mood, line)
            with Horizontal(id="summary-stats"):
                yield StatCard("Score", f"{round(s.score * 100)}%", f"{s.correct} of {s.total} correct")
                yield StatCard("XP earned", f"+{s.xp_earned}", f"{s.xp_total} total")
                yield StatCard("Streak", str(s.streak), "extended!" if s.streak_extended else "days")
                yield StatCard("Level", str(s.level), s.level_title)
            with Horizontal(id="summary-actions"):
                yield Button("Back home", id="btn-home", variant="primary")
                yield Button("Another round", id="btn-again")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#btn-home", Button).focus()
        self.prefetch_next()

    def action_home(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-home")
    def _home(self) -> None:
        self.action_home()

    @on(Button.Pressed, "#btn-again")
    def _again(self) -> None:
        self.app.pop_screen()
        from .home import HomeScreen

        screen = self.app.screen
        if isinstance(screen, HomeScreen):
            screen.action_start_session()

    @work(exclusive=True, group="prefetch", exit_on_error=False)
    async def prefetch_next(self) -> None:
        """Generate the next session in the background so tomorrow starts instantly."""
        store, cfg = self.app.store, self.app.config
        if store.cached_session():
            return
        try:
            exercises = await generate_session(store, cfg)
        except Exception:
            return
        store.cache_session(exercises)
