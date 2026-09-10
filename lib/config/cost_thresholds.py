"""Cost-estimate soft/hard thresholds (USD): project override with global default.

Priority per threshold: ``project.json`` plain top-level key (nullable) >
``ARCREEL_COST_{SOFT,HARD}_THRESHOLD_USD`` env var > built-in default. Pure —
no DB, no migration; the project fields are read like ``episode_target_duration``
(``docs/agents/project-migrations.md`` covers when a real migration is needed;
this is a nullable, additive field so none is required here).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

#: 与 ``lib.cost_estimate`` 的同名常量保持一致（不在此处 import——``lib.config`` 是分层契约的
#: 基础层，不得依赖 ``lib.custom_provider`` 之上的模块，即便只是经 ``lib.cost_estimate`` 间接可达）。
DEFAULT_SOFT_THRESHOLD_USD = 5.0
DEFAULT_HARD_THRESHOLD_USD = 20.0

SOFT_THRESHOLD_ENV_KEY = "ARCREEL_COST_SOFT_THRESHOLD_USD"
HARD_THRESHOLD_ENV_KEY = "ARCREEL_COST_HARD_THRESHOLD_USD"

#: project.json 顶层可选字段名；未在 ``patch_project`` 白名单中开放写入（见本分支报告 TODO）。
PROJECT_SOFT_THRESHOLD_KEY = "cost_soft_threshold_usd"
PROJECT_HARD_THRESHOLD_KEY = "cost_hard_threshold_usd"


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    parsed = _positive_float(_parse_str(raw))
    return parsed if parsed is not None else default


def _parse_str(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None


def cost_thresholds_usd(project: Mapping[str, Any] | None) -> tuple[float, float]:
    """Return ``(soft_threshold_usd, hard_threshold_usd)`` for this project."""

    soft_default = _env_float(SOFT_THRESHOLD_ENV_KEY, DEFAULT_SOFT_THRESHOLD_USD)
    hard_default = _env_float(HARD_THRESHOLD_ENV_KEY, DEFAULT_HARD_THRESHOLD_USD)
    if project is None:
        return soft_default, hard_default
    soft = _positive_float(project.get(PROJECT_SOFT_THRESHOLD_KEY))
    hard = _positive_float(project.get(PROJECT_HARD_THRESHOLD_KEY))
    return (soft if soft is not None else soft_default), (hard if hard is not None else hard_default)


__all__ = [
    "HARD_THRESHOLD_ENV_KEY",
    "PROJECT_HARD_THRESHOLD_KEY",
    "PROJECT_SOFT_THRESHOLD_KEY",
    "SOFT_THRESHOLD_ENV_KEY",
    "cost_thresholds_usd",
]
