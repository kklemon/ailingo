"""Command-line entry point: `ailingo` (TUI), `ailingo sync`, `ailingo remind`, `ailingo stats`."""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import find_dotenv, load_dotenv

from . import __version__
from .config import load_config, save_config
from .paths import config_path, db_path
from .store import Store


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(prog="ailingo", description="Personal English coach trained on your coding-agent prompts.")
    parser.add_argument("--version", action="version", version=f"ailingo {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_sync = sub.add_parser("sync", help="ingest new prompts and analyze them")
    p_sync.add_argument("--no-analyze", action="store_true", help="only ingest, do not call the model")
    p_sync.add_argument("--max", type=int, default=None, help="max prompts to analyze in this run")

    p_remind = sub.add_parser("remind", help="send a reminder notification if you have not practised today")
    p_remind.add_argument("--install", action="store_true", help="schedule the daily reminder (launchd / cron)")
    p_remind.add_argument("--uninstall", action="store_true", help="remove the scheduled reminder")
    p_remind.add_argument("--time", default=None, help="reminder time HH:MM (with --install)")
    p_remind.add_argument("--force", action="store_true", help="send the notification even if you practised today")

    sub.add_parser("stats", help="print progress and weak spots")
    sub.add_parser("sources", help="show which coding-agent transcripts were found")
    sub.add_parser("paths", help="print config and database locations")
    sub.add_parser("reset", help="forget the onboarding (keeps data)")

    args = parser.parse_args(argv)
    if args.command is None:
        return run_tui()
    if args.command == "sync":
        return run_sync(args)
    if args.command == "remind":
        return run_remind(args)
    if args.command == "stats":
        return run_stats()
    if args.command == "sources":
        return run_sources()
    if args.command == "paths":
        print(f"config: {config_path()}\ndata:   {db_path()}")
        return 0
    if args.command == "reset":
        cfg = load_config()
        cfg.onboarded = False
        save_config(cfg)
        print("Onboarding will run on the next start.")
        return 0
    parser.print_help()
    return 1


def run_tui() -> int:
    from .tui.app import AilingoApp

    config = load_config()
    store = Store(db_path())
    try:
        AilingoApp(config, store).run()
    finally:
        store.close()
    return 0


def run_sync(args: argparse.Namespace) -> int:
    from .analysis import analyze_pending
    from .ingest import ingest_all
    from .llm.client import LLMError, humanize_error

    config = load_config()
    store = Store(db_path())
    try:
        ingest_all(store, config, print)
        pending = store.pending_count()
        print(f"{pending} prompts waiting for analysis.")
        if args.no_analyze or not pending:
            return 0
        if not config.model:
            print("No model configured yet — start `ailingo` once to run the onboarding.", file=sys.stderr)
            return 2
        try:
            asyncio.run(analyze_pending(store, config, print, max_prompts=args.max))
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001
            print(f"error: {humanize_error(exc)}", file=sys.stderr)
            return 2
        return 0
    finally:
        store.close()


def run_remind(args: argparse.Namespace) -> int:
    from .gamification import compute_streak, practiced_today, say
    from .notify import (
        install_reminder,
        reminder_installed,
        send_notification,
        uninstall_reminder,
    )

    config = load_config()
    if args.install:
        when = args.time or config.notification_time
        try:
            msg = install_reminder(when)
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
            return 2
        config.notifications_enabled = True
        config.notification_time = when
        save_config(config)
        print(msg)
        return 0
    if args.uninstall:
        print(uninstall_reminder())
        config.notifications_enabled = False
        save_config(config)
        return 0
    store = Store(db_path())
    try:
        days = store.session_dates()
        if practiced_today(days) and not args.force:
            print("Already practised today — no reminder needed.")
            return 0
        streak = compute_streak(days)
        body = (
            f"Your {streak}-day streak is waiting. A few minutes, that's all." if streak else say("greet_evening")
        )
        sent = send_notification("ailingo — Quill would like a word", body)
        print("reminder sent" if sent else "could not send a notification on this platform")
        if not reminder_installed() and not config.notifications_enabled:
            print("tip: `ailingo remind --install --time 18:00` schedules this daily")
        return 0 if sent else 1
    finally:
        store.close()


def run_stats() -> int:
    from .gamification import compute_streak, level_for

    store = Store(db_path())
    try:
        xp = store.total_xp()
        level, title, next_xp = level_for(xp)
        streak = compute_streak(store.session_dates())
        print(f"Level {level} · {title} · {xp} XP" + (f" ({next_xp - xp} to next level)" if next_xp else ""))
        print(f"Streak: {streak} day(s) · Sessions: {store.sessions_completed()}")
        counts = store.prompt_counts()
        for source, c in counts.items():
            print(f"{source}: {c['usable']} usable prompts, {c['analyzed']} analyzed")
        patterns = store.patterns()
        print(f"\n{len(patterns)} weak spots:")
        for p in patterns[:25]:
            print(f"  {p.evidence_count:4d}×  {p.title}  [{p.category_label}]  mastery {round(p.mastery * 100)}%")
        return 0
    finally:
        store.close()


def run_sources() -> int:
    from .ingest import source_statuses

    for st in source_statuses():
        mark = "✔" if st.available else "✘"
        print(f"{mark} {st.label}: {st.location} — {st.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
