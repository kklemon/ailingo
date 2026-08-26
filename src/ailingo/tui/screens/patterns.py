from __future__ import annotations

from datetime import UTC, datetime

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Markdown

from ...practice import pattern_weight
from ...schemas import Pattern


class PatternsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        with Horizontal(id="patterns"):
            yield DataTable(id="patterns-table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="patterns-detail"):
                yield Markdown("", id="patterns-md")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Weak spot", "Category", "Seen", "Mastery")
        now = datetime.now(UTC)
        patterns = sorted(self.app.store.patterns(), key=lambda p: pattern_weight(p, now), reverse=True)
        self._by_key = {p.key: p for p in patterns}
        for p in patterns:
            table.add_row(p.title, p.category_label, str(p.evidence_count), _bar(p.mastery), key=p.key)
        if patterns:
            self.show(patterns[0])
        else:
            self.query_one("#patterns-md", Markdown).update(
                "# No weak spots yet\n\nRun **Sync & analyze** from the home screen so Quill can read your prompts."
            )

    @on(DataTable.RowHighlighted)
    def _highlight(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        pattern = self._by_key.get(str(event.row_key.value))
        if pattern:
            self.show(pattern)

    def show(self, p: Pattern) -> None:
        store = self.app.store
        examples = store.examples(p.id, limit=6)
        lines = [f"# {p.title}", f"*{p.category_label}* · seen {p.evidence_count}× · mastery {round(p.mastery * 100)}%", ""]
        if p.description:
            lines += ["## What you tend to do", p.description, ""]
        if p.correct_form:
            lines += ["## The correct form", p.correct_form, ""]
        if p.tip:
            lines += [f"> 💡 {p.tip}", ""]
        if examples:
            lines.append("## From your own prompts")
            for ex in examples:
                lines.append(f"- ~~{_md(ex.original)}~~ → **{_md(ex.corrected)}**")
                if ex.note and not p.description:
                    lines.append(f"  <br>{_md(ex.note)}")
            lines.append("")
        if p.times_practiced:
            lines.append(f"Practised {p.times_practiced}× · {p.times_correct} correct")
        self.query_one("#patterns-md", Markdown).update("\n".join(lines))


def _bar(value: float, width: int = 8) -> str:
    filled = round(max(0.0, min(1.0, value)) * width)
    return "█" * filled + "░" * (width - filled) + f" {round(value * 100):3d}%"


def _md(text: str) -> str:
    return text.replace("*", "\\*").replace("_", "\\_").replace("~", "\\~").replace("\n", " ")
