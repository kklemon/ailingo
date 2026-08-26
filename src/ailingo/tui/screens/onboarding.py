"""First-launch wizard: provider → model → API key → connection test → sources → first sync."""

from __future__ import annotations

import os

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option

from ...config import PROVIDERS, env_var_for_model
from ...ingest import source_statuses
from ...llm.client import LLMError, test_connection
from ..widgets import Mascot

STEPS = ["welcome", "provider", "model", "key", "test", "sources", "done"]


class OnboardingScreen(Screen):
    BINDINGS = [Binding("escape", "back", "Back", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.step = 0
        self.provider = "openai"
        self.model = PROVIDERS["openai"].default_model
        self.api_key = ""
        self.user_name = ""
        self.sources: dict[str, bool] = {}
        self._test_ok = False

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard"):
            yield Static("Welcome to ailingo", classes="title", id="wizard-title")
            yield Mascot("happy", "", id="wizard-mascot")
            yield Vertical(id="step")
            with Horizontal(id="nav"):
                yield Button("Back", id="btn-back")
                yield Button("Continue", id="btn-next", variant="primary")
        yield Footer()

    async def on_mount(self) -> None:
        await self.show_step()

    # -------------------------------------------------------------- steps --

    async def show_step(self) -> None:
        name = STEPS[self.step]
        container = self.query_one("#step", Vertical)
        await container.remove_children()
        mascot = self.query_one("#wizard-mascot", Mascot)
        title = self.query_one("#wizard-title", Static)
        back = self.query_one("#btn-back", Button)
        nxt = self.query_one("#btn-next", Button)
        back.disabled = self.step == 0
        nxt.disabled = False
        nxt.label = "Continue"
        builder = getattr(self, f"_step_{name}")
        widgets, mood, line, heading = builder()
        title.update(heading)
        mascot.set(mood, line)
        await container.mount(*widgets)
        focusable = list(container.query("Input, RadioSet, OptionList, SelectionList"))
        if focusable:
            focusable[0].focus()
        else:
            nxt.focus()
        if name == "test":
            nxt.disabled = True
            self.run_test()

    def _step_welcome(self):
        return (
            [
                Static(
                    "I'm Quill. I'll read the prompts you write to Codex, Claude Code and friends, "
                    "find the English mistakes you keep making, and turn them into a few minutes of "
                    "practice per day.\n\nFirst, I need a language model to do the reading. "
                    "This takes about a minute to set up."
                ),
                Label("What should I call you? (optional)", classes="field-label"),
                Input(value=self.user_name, placeholder="your name", id="in-name"),
            ],
            "happy",
            "Hi. I've heard about your prompts. We should talk.",
            "Welcome to ailingo",
        )

    def _step_provider(self):
        buttons = [
            RadioButton(f"{info.label} — {info.blurb}", value=(pid == self.provider), id=f"prov-{pid}")
            for pid, info in PROVIDERS.items()
        ]
        return (
            [Label("Which LLM provider do you want to use?", classes="field-label"), RadioSet(*buttons, id="providers")],
            "thinking",
            "Pick a brain. Any of them will do; the cheap ones are plenty.",
            "Step 1 · Provider",
        )

    def _step_model(self):
        info = PROVIDERS[self.provider]
        if not self.model.startswith(info.prefix + ":") and info.prefix:
            self.model = info.default_model
        widgets = [
            Label("Model id (Pydantic AI format: provider:model). Pick a suggestion or type your own.", classes="field-label"),
            Input(value=self.model, id="in-model"),
        ]
        if info.prefix:
            widgets.append(
                OptionList(*[Option(f"{info.prefix}:{m}", id=f"{info.prefix}:{m}") for m in info.suggested_models], id="model-suggestions")
            )
        else:
            widgets.append(Static("Examples: " + ", ".join(info.suggested_models), classes="muted"))
        return widgets, "thinking", "Smaller models are fine for this — I'm the one doing the judging.", "Step 2 · Model"

    def _step_key(self):
        env_var = env_var_for_model(self.model)
        info = PROVIDERS[self.provider]
        if env_var is None:
            return (
                [Static("This provider reads its credentials from its own environment variables. Make sure they are set before continuing.")],
                "thinking",
                "I trust you have the credentials sorted.",
                "Step 3 · API key",
            )
        found = os.environ.get(env_var)
        widgets = [
            Label(f"API key for {info.label} ({env_var}). Get one at {info.key_url}", classes="field-label"),
            Input(value=self.api_key, password=True, placeholder="paste your key" if not found else f"leave blank to use {env_var} from the environment", id="in-key"),
        ]
        if found:
            widgets.insert(0, Static(f"✔ {env_var} is already set in your environment. Leave the field blank to use it.", classes="success"))
        return widgets, "happy", "I'll store it locally, permissions 600, no funny business.", "Step 3 · API key"

    def _step_test(self):
        return (
            [Static("Contacting the model …", id="test-status")],
            "thinking",
            "Knock knock. Let's see if anyone answers.",
            "Step 4 · Connection test",
        )

    def _step_sources(self):
        items = []
        for st in source_statuses():
            label = f"{st.label} — {st.detail}" if st.available else f"{st.label} — not found at {st.location}"
            if st.available:
                items.append((label, st.name, self.sources.get(st.name, True)))
        widgets: list = [Label("Which coding agents should I read prompts from?", classes="field-label")]
        if items:
            widgets.append(SelectionList[str](*items, id="sources"))
        else:
            widgets.append(Static("I could not find any transcripts on this machine. You can still continue; nothing to read yet.", classes="error"))
        missing = [st for st in source_statuses() if not st.available]
        if missing:
            widgets.append(Static("Not found: " + ", ".join(f"{st.label} ({st.location})" for st in missing), classes="muted"))
        return widgets, "happy", "Your prompts. All of them. Don't worry, I've seen worse.", "Step 5 · Sources"

    def _step_done(self):
        cfg = self.app.config
        return (
            [
                Static(
                    f"All set. Next, I'll read up to {cfg.max_prompts_per_run} of your most recent prompts "
                    f"(about {max(1, cfg.max_prompts_per_run // 18)} model calls, roughly a minute or two) "
                    "and build your list of weak spots. After that you can start practising.\n\n"
                    "You can change everything later in Settings, and run 'ailingo sync' from the shell."
                )
            ],
            "proud",
            "Let's read. I've cleared my afternoon.",
            "Ready",
        )

    # ------------------------------------------------------------- events --

    @on(RadioSet.Changed, "#providers")
    def _provider_changed(self, event: RadioSet.Changed) -> None:
        pid = str(event.pressed.id or "").removeprefix("prov-")
        if pid in PROVIDERS:
            self.provider = pid

    @on(OptionList.OptionSelected, "#model-suggestions")
    def _suggestion(self, event: OptionList.OptionSelected) -> None:
        self.query_one("#in-model", Input).value = str(event.option.id)
        self.query_one("#btn-next", Button).focus()

    @on(Input.Submitted)
    def _submitted(self) -> None:
        self.advance()

    @on(Button.Pressed, "#btn-next")
    def _next(self) -> None:
        self.advance()

    @on(Button.Pressed, "#btn-back")
    def _back(self) -> None:
        self.action_back()

    def action_back(self) -> None:
        if self.step > 0:
            self.step -= 1
            if STEPS[self.step] == "test":
                self.step -= 1
            self.call_later(self.show_step)

    def _collect(self) -> bool:
        name = STEPS[self.step]
        if name == "welcome":
            self.user_name = self.query_one("#in-name", Input).value.strip()
        elif name == "model":
            model = self.query_one("#in-model", Input).value.strip()
            if ":" not in model:
                self.notify("Use the provider:model format, e.g. openai:gpt-5.6-terra", severity="error")
                return False
            self.model = model
        elif name == "key":
            try:
                self.api_key = self.query_one("#in-key", Input).value.strip()
            except Exception:
                self.api_key = ""
            env_var = env_var_for_model(self.model)
            if env_var and not self.api_key and not os.environ.get(env_var):
                self.notify("I need a key to talk to the model.", severity="error")
                return False
            if env_var and self.api_key:
                os.environ[env_var] = self.api_key
        elif name == "sources":
            try:
                selected = set(self.query_one("#sources", SelectionList).selected)
                self.sources = {st.name: (st.name in selected) for st in source_statuses() if st.available}
            except Exception:
                self.sources = {}
        return True

    def advance(self) -> None:
        if not self._collect():
            return
        if STEPS[self.step] == "done":
            self.finish()
            return
        self.step += 1
        self.call_later(self.show_step)

    @work(exclusive=True, group="test", exit_on_error=False)
    async def run_test(self) -> None:
        status = self.query_one("#test-status", Static)
        mascot = self.query_one("#wizard-mascot", Mascot)
        cfg = self.app.config.model_copy(deep=True)
        env_var = env_var_for_model(self.model)
        if env_var and self.api_key:
            cfg.api_keys[env_var] = self.api_key
        try:
            reply = await test_connection(cfg, self.model)
        except LLMError as exc:
            status.update(f"✘ {exc}\n\nPress Back to fix the model or the key.")
            status.set_classes("error")
            mascot.set("shocked", "Nobody home. Check the model id and the key.")
            self._test_ok = False
            return
        status.update(f"✔ {self.model} answered: “{reply[:80]}”")
        status.set_classes("success")
        mascot.set("proud", "It's alive. Continue.")
        self._test_ok = True
        nxt = self.query_one("#btn-next", Button)
        nxt.disabled = False
        nxt.focus()

    def finish(self) -> None:
        cfg = self.app.config
        cfg.model = self.model
        cfg.user_name = self.user_name
        env_var = env_var_for_model(self.model)
        if env_var and self.api_key:
            cfg.api_keys[env_var] = self.api_key
        for name, enabled in self.sources.items():
            cfg.sources[name] = enabled
        cfg.onboarded = True
        self.app.save_config()
        from .sync import SyncScreen

        self.app.pop_screen()
        self.app.push_screen(SyncScreen())
