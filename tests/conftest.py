"""Global test isolation for mutable application state."""

from __future__ import annotations

import pytest

from core.config import AppConfig, config_manager


@pytest.fixture(autouse=True)
def isolate_user_config(tmp_path, monkeypatch):
    """Never allow a test to read or write the real desktop configuration."""

    config_path = tmp_path / "user-config.json"
    monkeypatch.setenv("ECHOVAULT_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_manager, "config_path", config_path)
    monkeypatch.setattr(config_manager, "config", AppConfig())
    monkeypatch.setattr(config_manager, "_loaded", False)
    monkeypatch.setattr(config_manager, "recovered_from_backup", None)
    yield
