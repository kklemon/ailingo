"""Turn ingested prompts into an evolving set of mistake patterns."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .config import Config
from .llm import prompts as P
from .llm.client import LLMError, build_model, humanize_error, make_agent
from .schemas import BatchAnalysis, Consolidation
from .store import PromptRow, Store

BATCH_SIZE = 18
CONCURRENCY = 4
CONSOLIDATE_EVERY_FINDINGS = 25

Log = Callable[[str], None]


@dataclass
class AnalysisReport:
    prompts_analyzed: int = 0
    findings: int = 0
    typos_ignored: int = 0
    new_patterns: int = 0
    updated_patterns: int = 0
    consolidated: bool = False
    batches_failed: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = "done"


def analysis_is_due(store: Store, config: Config, min_new_prompts: int = 10) -> bool:
    if store.pending_count() < min_new_prompts:
        return False
    last = store.get_dt("last_analysis_at")
    if last is None:
        return True
    return datetime.now(UTC) - last >= timedelta(days=config.analysis_interval_days)


def _format_batch(batch: list[PromptRow], existing: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    if existing:
        lines.append("EXISTING PATTERNS (reuse these keys when applicable):")
        for key, title in existing[:80]:
            lines.append(f"- {key}: {title}")
        lines.append("")
    lines.append("PROMPTS:")
    for i, row in enumerate(batch):
        text = row.text.replace("\n", "\n    ")
        lines.append(f"[{i}] {text}")
        lines.append("")
    return "\n".join(lines)


async def analyze_pending(
    store: Store,
    config: Config,
    log: Log | None = None,
    *,
    max_prompts: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> AnalysisReport:
    """Analyze un-analyzed prompts in batches, upsert patterns, consolidate when warranted."""
    say = log or (lambda _msg: None)
    report = AnalysisReport()
    limit = max_prompts if max_prompts is not None else config.max_prompts_per_run
    rows = store.pending_prompts(limit=limit)
    if not rows:
        say("Nothing new to analyze.")
        return report

    model = build_model(config)
    analyzer = make_agent(model, BatchAnalysis, P.ANALYZER)
    run_id = store.start_run(config.model)
    batches = [rows[i : i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    say(f"Analyzing {len(rows)} prompts in {len(batches)} batches with {config.model} …")
    if progress:
        progress(0, len(batches))

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    done = 0

    async def run_batch(index: int, batch: list[PromptRow]) -> None:
        nonlocal done
        async with sem:
            existing = [(p.key, p.title) for p in store.patterns()]
            try:
                result = await analyzer.run(_format_batch(batch, existing))
                analysis: BatchAnalysis = result.output
            except Exception as exc:
                async with lock:
                    report.batches_failed += 1
                    report.errors.append(humanize_error(exc))
                    done += 1
                    say(f"Batch {index + 1}/{len(batches)} failed: {humanize_error(exc)}")
                    if progress:
                        progress(done, len(batches))
                return
        async with lock:
            _apply_findings(store, batch, analysis, report)
            store.mark_analyzed(r.id for r in batch)
            report.prompts_analyzed += len(batch)
            done += 1
            say(
                f"Batch {index + 1}/{len(batches)}: {len(analysis.findings)} findings "
                f"({sum(1 for f in analysis.findings if f.one_off_typo)} typos ignored)"
            )
            if progress:
                progress(done, len(batches))

    await asyncio.gather(*(run_batch(i, b) for i, b in enumerate(batches)))

    if report.batches_failed == len(batches):
        report.status = "failed"
        store.finish_run(
            run_id,
            prompts=0,
            findings=0,
            typos=0,
            status="failed",
            error=report.errors[0] if report.errors else "all batches failed",
        )
        raise LLMError(report.errors[0] if report.errors else "Every batch failed.")

    since = int(store.get("findings_since_consolidation", "0") or 0) + report.findings
    active = store.patterns()
    if active and (report.new_patterns > 0 or since >= CONSOLIDATE_EVERY_FINDINGS):
        say("Consolidating patterns …")
        try:
            await consolidate(store, config, say)
            report.consolidated = True
            store.set("findings_since_consolidation", "0")
        except Exception as exc:
            report.errors.append(f"Consolidation failed: {humanize_error(exc)}")
            say(report.errors[-1])
            store.set("findings_since_consolidation", str(since))
    else:
        store.set("findings_since_consolidation", str(since))

    store.finish_run(
        run_id,
        prompts=report.prompts_analyzed,
        findings=report.findings,
        typos=report.typos_ignored,
        status="done",
        error="; ".join(report.errors) if report.errors else None,
    )
    store.clear_practice_cache()
    say(
        f"Done: {report.prompts_analyzed} prompts, {report.findings} findings, "
        f"{report.new_patterns} new patterns, {report.typos_ignored} typos ignored."
    )
    return report


def _apply_findings(store: Store, batch: list[PromptRow], analysis: BatchAnalysis, report: AnalysisReport) -> None:
    for f in analysis.findings:
        if f.one_off_typo:
            report.typos_ignored += 1
            continue
        if not (0 <= f.prompt_index < len(batch)):
            continue
        row = batch[f.prompt_index]
        key = _normalize_key(f.pattern_key)
        if not key:
            continue
        before = store.pattern_by_key(key)
        pattern = store.upsert_pattern(
            key=key,
            category=f.category,
            title=f.title.strip() or key.replace("_", " "),
            explanation=f.explanation.strip(),
            seen_at=row.created_at,
        )
        if before is None:
            report.new_patterns += 1
        else:
            report.updated_patterns += 1
        store.add_example(pattern.id, row.id, f.original, f.corrected, f.explanation)
        report.findings += 1


def _normalize_key(key: str) -> str:
    key = key.strip().lower().replace("-", "_").replace(" ", "_")
    key = "".join(ch for ch in key if ch.isalnum() or ch == "_")
    return key.strip("_")[:60]


def _format_patterns_for_consolidation(store: Store) -> str:
    lines: list[str] = []
    for p in store.patterns():
        lines.append(f"### {p.key}")
        lines.append(f"category: {p.category} | title: {p.title} | evidence: {p.evidence_count}")
        if p.description:
            lines.append(f"description: {p.description}")
        if p.correct_form:
            lines.append(f"rule: {p.correct_form}")
        for ex in store.examples(p.id, limit=4):
            lines.append(f'- "{ex.original}" -> "{ex.corrected}"')
        lines.append("")
    return "\n".join(lines)


async def consolidate(store: Store, config: Config, log: Log | None = None) -> None:
    say = log or (lambda _msg: None)
    active = store.patterns()
    if not active:
        return
    model = build_model(config)
    agent = make_agent(model, Consolidation, P.CONSOLIDATOR)
    result = await agent.run("CURRENT PATTERNS:\n\n" + _format_patterns_for_consolidation(store))
    consolidation: Consolidation = result.output
    by_key = {p.key: p for p in active}
    claimed: set[str] = set()
    merges = 0
    for spec in consolidation.patterns:
        keys = [_normalize_key(k) for k in [spec.key, *spec.merged_keys]]
        keys = [k for k in keys if k in by_key and k not in claimed]
        if not keys:
            continue
        canonical_key = _normalize_key(spec.key) if _normalize_key(spec.key) in keys else keys[0]
        canonical = by_key[canonical_key]
        for k in keys:
            claimed.add(k)
            if k != canonical_key:
                store.merge_patterns(canonical.id, by_key[k].id)
                merges += 1
        store.update_pattern_text(
            canonical.id,
            category=spec.category,
            title=spec.title.strip() or canonical.title,
            description=spec.description.strip(),
            correct_form=spec.correct_form.strip(),
            tip=spec.tip.strip(),
        )
    say(f"Consolidated: {len(claimed)} patterns reviewed, {merges} merged.")
