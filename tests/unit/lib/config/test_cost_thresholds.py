"""``lib.config.cost_thresholds``：project 覆盖 > env > 内置默认，三级回落。"""

from __future__ import annotations

from lib.config.cost_thresholds import (
    DEFAULT_HARD_THRESHOLD_USD,
    DEFAULT_SOFT_THRESHOLD_USD,
    HARD_THRESHOLD_ENV_KEY,
    PROJECT_HARD_THRESHOLD_KEY,
    PROJECT_SOFT_THRESHOLD_KEY,
    SOFT_THRESHOLD_ENV_KEY,
    cost_thresholds_usd,
)


def test_no_project_and_no_env_falls_back_to_builtin_defaults(monkeypatch):
    monkeypatch.delenv(SOFT_THRESHOLD_ENV_KEY, raising=False)
    monkeypatch.delenv(HARD_THRESHOLD_ENV_KEY, raising=False)
    assert cost_thresholds_usd(None) == (DEFAULT_SOFT_THRESHOLD_USD, DEFAULT_HARD_THRESHOLD_USD)


def test_env_overrides_builtin_default(monkeypatch):
    monkeypatch.setenv(SOFT_THRESHOLD_ENV_KEY, "1.5")
    monkeypatch.setenv(HARD_THRESHOLD_ENV_KEY, "9")
    assert cost_thresholds_usd(None) == (1.5, 9.0)


def test_project_overrides_env(monkeypatch):
    monkeypatch.setenv(SOFT_THRESHOLD_ENV_KEY, "1.5")
    monkeypatch.setenv(HARD_THRESHOLD_ENV_KEY, "9")
    project = {PROJECT_SOFT_THRESHOLD_KEY: 3.0, PROJECT_HARD_THRESHOLD_KEY: 40.0}
    assert cost_thresholds_usd(project) == (3.0, 40.0)


def test_project_field_present_but_invalid_falls_back(monkeypatch):
    monkeypatch.delenv(SOFT_THRESHOLD_ENV_KEY, raising=False)
    monkeypatch.delenv(HARD_THRESHOLD_ENV_KEY, raising=False)
    project = {PROJECT_SOFT_THRESHOLD_KEY: "not-a-number", PROJECT_HARD_THRESHOLD_KEY: -5}
    assert cost_thresholds_usd(project) == (DEFAULT_SOFT_THRESHOLD_USD, DEFAULT_HARD_THRESHOLD_USD)


def test_project_missing_fields_falls_back_to_env_or_default(monkeypatch):
    monkeypatch.delenv(SOFT_THRESHOLD_ENV_KEY, raising=False)
    monkeypatch.delenv(HARD_THRESHOLD_ENV_KEY, raising=False)
    assert cost_thresholds_usd({}) == (DEFAULT_SOFT_THRESHOLD_USD, DEFAULT_HARD_THRESHOLD_USD)
