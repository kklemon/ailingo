"""System notifications and a scheduled daily reminder (launchd on macOS, cron on Linux)."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.ailingo.reminder"


def send_notification(title: str, body: str) -> bool:
    if sys.platform == "darwin":
        script = f'display notification "{_esc(body)}" with title "{_esc(title)}" sound name "Pop"'
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
            return True
        except (OSError, subprocess.SubprocessError):
            return False
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", title, body], check=True, capture_output=True, timeout=10)
            return True
        except (OSError, subprocess.SubprocessError):
            return False
    return False


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def ailingo_executable() -> str:
    found = shutil.which("ailingo")
    if found:
        return found
    return os.path.abspath(sys.argv[0])


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = value.strip().split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
    except ValueError as exc:
        raise ValueError(f"Invalid time '{value}', expected HH:MM") from exc
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time '{value}', expected HH:MM")
    return hour, minute


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install_reminder(time_str: str) -> str:
    """Schedule `ailingo remind` daily. Returns a human-readable description."""
    hour, minute = _parse_time(time_str)
    exe = ailingo_executable()
    if sys.platform == "darwin":
        plist = {
            "Label": LABEL,
            "ProgramArguments": [exe, "remind"],
            "StartCalendarInterval": {"Hour": hour, "Minute": minute},
            "RunAtLoad": False,
            "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
        }
        path = _plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        path.write_bytes(plistlib.dumps(plist))
        res = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"launchctl load failed: {res.stderr.strip() or res.stdout.strip()}")
        return f"launchd job {LABEL} installed at {path} ({hour:02d}:{minute:02d} daily)"
    if shutil.which("crontab"):
        line = f"{minute} {hour} * * * {exe} remind # {LABEL}"
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = [ln for ln in current.stdout.splitlines() if LABEL not in ln] if current.returncode == 0 else []
        new = "\n".join([*existing, line]) + "\n"
        res = subprocess.run(["crontab", "-"], input=new, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"crontab failed: {res.stderr.strip()}")
        return f"cron entry installed ({hour:02d}:{minute:02d} daily)"
    raise RuntimeError("No scheduler available on this platform (need launchd or crontab).")


def uninstall_reminder() -> str:
    if sys.platform == "darwin":
        path = _plist_path()
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            path.unlink()
            return "launchd reminder removed"
        return "no launchd reminder installed"
    if shutil.which("crontab"):
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if current.returncode != 0:
            return "no crontab"
        kept = [ln for ln in current.stdout.splitlines() if LABEL not in ln]
        subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", capture_output=True, text=True)
        return "cron reminder removed"
    return "nothing to remove"


def reminder_installed() -> bool:
    if sys.platform == "darwin":
        return _plist_path().exists()
    if shutil.which("crontab"):
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return current.returncode == 0 and LABEL in current.stdout
    return False
