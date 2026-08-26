"""Filesystem locations for config and data (overridable via env vars)."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "ailingo"


def config_dir() -> Path:
    override = os.environ.get("AILINGO_CONFIG_DIR")
    path = Path(override).expanduser() if override else Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    override = os.environ.get("AILINGO_DATA_DIR")
    path = Path(override).expanduser() if override else Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "ailingo.db"
