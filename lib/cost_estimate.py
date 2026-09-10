"""Pure per-unit cost estimation and ``cost_estimate`` aggregation.

Generalizes the reference-video quoting pattern in
``server.services.cost_estimation.quote_video_request_from_price`` to the
other media types (``image`` / ``audio``) so ``lib.workflow_plan`` can attach
a ``cost_estimate`` to generation ``next_action``s. Stays pure and I/O-free
like ``lib.cost_calculator`` / ``lib.pricing.strategies``: callers resolve the
provider/model identity and (for custom providers) the declared price before
calling in — this module never touches the filesystem, the DB or the queue.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from lib.cost_calculator import cost_calculator
from lib.custom_provider import is_custom_provider
from lib.pricing.strategies import PricingParams

#: Global fallback thresholds (USD) when neither the project nor the
#: ``ARCREEL_COST_*_THRESHOLD_USD`` env vars declare one. See ``lib.config.cost_thresholds``.
DEFAULT_SOFT_THRESHOLD_USD = 5.0
DEFAULT_HARD_THRESHOLD_USD = 20.0

CostThreshold = Literal["ok", "warn", "confirm"]
CostCallType = Literal["video", "image", "audio"]


@dataclass(frozen=True, slots=True)
class UnitCostEstimate:
    """One unit's estimated cost at its resolved provider/model identity."""

    amount: float
    currency: str
    provider_id: str
    model_id: str

    def to_payload(self) -> dict[str, object]:
        return {"amount": self.amount, "currency": self.currency}


def estimate_unit_cost(
    *,
    call_type: CostCallType,
    provider_id: str,
    model_id: str | None,
    resolution: str | None = None,
    duration_seconds: int | None = None,
    generate_audio: bool = True,
    character_count: int | None = None,
    image_count: int = 1,
    custom_price_input: float | None = None,
    custom_price_output: float | None = None,
    custom_currency: str | None = None,
) -> UnitCostEstimate | None:
    """One unit's cost, or ``None`` when this provider/model has no known price.

    Built-in providers always resolve to a price via ``lookup_pricing``'s
    fallback chains (see ``lib.pricing.lookup``) and therefore never return
    ``None`` here. Custom providers with no declared price
    (``custom_price_input is None``) return ``None`` rather than a misleading
    zero amount — the caller (``lib.workflow_plan``) surfaces those unit ids
    under ``unpriced_units`` instead of folding them into the total.
    """

    if is_custom_provider(provider_id) and custom_price_input is None:
        return None

    amount, currency = cost_calculator.calculate_cost(
        provider_id,
        PricingParams(
            call_type=call_type,
            model=model_id,
            resolution=resolution,
            duration_seconds=duration_seconds,
            generate_audio=generate_audio,
            usage_tokens=character_count,
            n=max(1, image_count),
        ),
        custom_price_input=custom_price_input,
        custom_price_output=custom_price_output,
        custom_currency=custom_currency,
        estimate_only=True,
    )
    if call_type == "image" and image_count > 1 and custom_price_input is not None:
        # 自定义供应商按张计费（``_calculate_custom_cost`` 未消费 ``n``），非自定义图片形状
        # （``per_image_*``）多数亦未消费 ``n``；显式按 image_count 折算，避免多图请求漏计。
        amount *= image_count
    return UnitCostEstimate(round(amount, 6), currency, provider_id, model_id or "")


#: One priced unit's serialized amount, or ``None`` for an unpriced unit. Accepts either an
#: ``UnitCostEstimate`` (as produced by ``estimate_unit_cost``) or its already-serialized
#: ``{"amount": ..., "currency": ...}`` payload (as carried on a ``lib.batch_admission``
#: ticket's ``request_cost``) — ``lib.workflow_plan`` stays pure and only ever sees payloads.
UnitCostInput = UnitCostEstimate | Mapping[str, object] | None


def _unit_amount_currency(estimate: UnitCostInput) -> tuple[float, str] | None:
    if estimate is None:
        return None
    if isinstance(estimate, UnitCostEstimate):
        return estimate.amount, estimate.currency
    amount = estimate.get("amount")
    currency = estimate.get("currency")
    if (
        not isinstance(amount, (int, float))
        or isinstance(amount, bool)
        or not isinstance(currency, str)
        or not currency
    ):
        return None
    return float(amount), currency


def aggregate_cost_estimate(
    units: Mapping[str, UnitCostInput],
    *,
    soft_threshold_usd: float,
    hard_threshold_usd: float,
) -> dict[str, object]:
    """Fold per-unit estimates into the ``WorkflowNextAction.cost_estimate`` shape.

    ``total`` is only populated when every priced unit shares one currency —
    a partial sum across currencies would understate or misstate what the
    user is agreeing to. When ``total`` is ``None`` (no priced units, or a
    currency mismatch), ``threshold`` falls back to ``"ok"``: without a
    single comparable total there is nothing to gate on, and the unpriced /
    mixed-currency units are already visible via ``unpriced_units`` for the
    caller to reason about explicitly.
    """

    resolved = {unit_id: _unit_amount_currency(estimate) for unit_id, estimate in units.items()}
    priced = {unit_id: value for unit_id, value in resolved.items() if value is not None}
    unpriced_ids = sorted(unit_id for unit_id, value in resolved.items() if value is None)
    currencies = {currency for _amount, currency in priced.values()}

    total: dict[str, object] | None = None
    if priced and len(currencies) == 1:
        total = {
            "amount": round(sum(amount for amount, _currency in priced.values()), 6),
            "currency": next(iter(currencies)),
        }

    threshold: CostThreshold = "ok"
    if total is not None and total["currency"] == "USD":
        amount = total["amount"]
        assert isinstance(amount, (int, float))
        if amount >= hard_threshold_usd:
            threshold = "confirm"
        elif amount >= soft_threshold_usd:
            threshold = "warn"

    return {
        "units": {unit_id: {"amount": amount, "currency": currency} for unit_id, (amount, currency) in priced.items()},
        "total": total,
        "unpriced_units": unpriced_ids,
        "threshold": threshold,
    }


__all__ = [
    "DEFAULT_HARD_THRESHOLD_USD",
    "DEFAULT_SOFT_THRESHOLD_USD",
    "CostCallType",
    "CostThreshold",
    "UnitCostEstimate",
    "aggregate_cost_estimate",
    "estimate_unit_cost",
]
