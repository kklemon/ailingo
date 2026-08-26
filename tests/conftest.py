from __future__ import annotations

from pathlib import Path

import pytest

from ailingo.config import Config
from ailingo.store import Store


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AILINGO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AILINGO_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def config() -> Config:
    return Config(model="test:fake", onboarded=True)
