from __future__ import annotations

import os

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static, Switch

from ...config import env_var_for_model
from ...ingest import source_statuses
from ...llm.client import LLMError, test_connection
from ...notify import install_reminder, reminder_installed, uninstall_reminder


class SettingsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Cancel")]

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        with Vertical(id="settings"):
            yield Static("Settings", classes="title")
            with VerticalScroll(id="settings-form"):
                yield Static(
                    "Model — a Pydantic AI id such as openai:gpt-5.6-terra, anthropic:claude-sonnet-5, "
                    "google:gemini-3.7-flash or openrouter:vendor/model",
                    classes="field-label",
                )
                yield Input(value=cfg.model or "", placeholder="provider:model", id="in-model")
                yield Static(self._key_label(cfg.model or ""), classes="field-label", id="lbl-key")
                yield Input(value=self._current_key(cfg.model or ""), password=True, placeholder="API key (leave blank to use the environment)", id="in-key")
                with Horizontal(classes="row"):
                    yield Button("Test connection", id="btn-test")
                    yield Static("", id="test-result")
                yield Label("Your name (optional, for the duck)", classes="field-label")
                yield Input(value=cfg.user_name, id="in-name")
                yield Label("Sources", classes="field-label")
                for status in source_statuses():
                    with Horizontal(classes="row"):
                        yield Label(f"{status.label} — {status.detail}")
                        yield Switch(value=cfg.source_enabled(status.name), id=f"src-{status.name}", disabled=not status.available)
                yield Label("Exercises per session", classes="field-label")
                yield Input(value=str(cfg.exercises_per_session), type="integer", id="in-count")
                yield Label("Max prompts analyzed per sync", classes="field-label")
                yield Input(value=str(cfg.max_prompts_per_run), type="integer", id="in-max")
                with Horizontal(classes="row"):
                    yield Label(f"Auto-analyze new prompts every {cfg.analysis_interval_days} days on startup")
                    yield Switch(value=cfg.auto_analyze, id="sw-auto")
                with Horizontal(classes="row"):
                    yield Label("Daily reminder notification" + (" (installed)" if reminder_installed() else ""))
                    yield Switch(value=cfg.notifications_enabled, id="sw-notify")
                yield Label("Reminder time (HH:MM)", classes="field-label")
                yield Input(value=cfg.notification_time, placeholder="18:00", id="in-time")
            with Horizontal(id="settings-actions"):
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def _key_label(self, model: str) -> str:
        env_var = env_var_for_model(model)
        if env_var is None:
            return "API key (this provider's key is read from its own environment variable)"
        if os.environ.get(env_var) and env_var not in self.app.config.api_keys:
            return f"API key — {env_var} found in the environment, leave blank to keep using it"
        return f"API key ({env_var})"

    def _current_key(self, model: str) -> str:
        env_var = env_var_for_model(model)
        return self.app.config.api_keys.get(env_var, "") if env_var else ""

    @on(Input.Changed, "#in-model")
    def _model_changed(self, event: Input.Changed) -> None:
        self.query_one("#lbl-key", Static).update(self._key_label(event.value.strip()))

    @on(Button.Pressed, "#btn-test")
    def _test(self) -> None:
        self.run_test()

    @work(exclusive=True, group="test", exit_on_error=False)
    async def run_test(self) -> None:
        model = self.query_one("#in-model", Input).value.strip()
        key = self.query_one("#in-key", Input).value.strip()
        result = self.query_one("#test-result", Static)
        result.update("testing …")
        env_var = env_var_for_model(model)
        cfg = self.app.config.model_copy(deep=True)
        if env_var and key:
            cfg.api_keys[env_var] = key
            os.environ[env_var] = key
        try:
            reply = await test_connection(cfg, model)
        except LLMError as exc:
            result.update(f"✘ {exc}")
            result.set_classes("error")
            return
        result.update(f"✔ {reply[:60]}")
        result.set_classes("success")

    @on(Button.Pressed, "#btn-cancel")
    def _cancel(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-save")
    def _save(self) -> None:
        cfg = self.app.config
        model = self.query_one("#in-model", Input).value.strip()
        if ":" not in model:
            self.notify("Model must look like provider:model", severity="error")
            return
        cfg.model = model
        env_var = env_var_for_model(model)
        key = self.query_one("#in-key", Input).value.strip()
        if env_var:
            if key:
                cfg.api_keys[env_var] = key
                os.environ[env_var] = key
            else:
                cfg.api_keys.pop(env_var, None)
        cfg.user_name = self.query_one("#in-name", Input).value.strip()
        for status in source_statuses():
            try:
                cfg.sources[status.name] = self.query_one(f"#src-{status.name}", Switch).value
            except Exception:
                pass
        try:
            cfg.exercises_per_session = max(3, min(15, int(self.query_one("#in-count", Input).value or 6)))
            cfg.max_prompts_per_run = max(20, int(self.query_one("#in-max", Input).value or 300))
        except ValueError:
            self.notify("Numbers, please.", severity="error")
            return
        cfg.auto_analyze = self.query_one("#sw-auto", Switch).value
        cfg.notification_time = self.query_one("#in-time", Input).value.strip() or "18:00"
        want_notify = self.query_one("#sw-notify", Switch).value
        try:
            if want_notify:
                msg = install_reminder(cfg.notification_time)
                self.notify(msg, timeout=6)
            elif cfg.notifications_enabled or reminder_installed():
                uninstall_reminder()
            cfg.notifications_enabled = want_notify
        except Exception as exc:
            self.notify(f"Reminder not changed: {exc}", severity="error", timeout=8)
            cfg.notifications_enabled = reminder_installed()
        self.app.save_config()
        self.notify("Settings saved.")
        self.app.pop_screen()
