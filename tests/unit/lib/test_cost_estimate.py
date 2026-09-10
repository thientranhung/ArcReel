"""``lib.cost_estimate``：built-in / custom-unpriced 分支、聚合、阈值判定、多币种回落。"""

from __future__ import annotations

from lib.cost_estimate import (
    UnitCostEstimate,
    aggregate_cost_estimate,
    estimate_unit_cost,
)


class TestEstimateUnitCost:
    def test_builtin_video_provider_always_priced(self):
        estimate = estimate_unit_cost(
            call_type="video",
            provider_id="gemini-aistudio",
            model_id="veo-3.1-lite-generate-preview",
            duration_seconds=8,
        )
        assert estimate is not None
        assert estimate.amount > 0
        assert estimate.currency

    def test_custom_provider_without_price_is_unpriced(self):
        estimate = estimate_unit_cost(
            call_type="image",
            provider_id="custom-3",
            model_id="some-model",
            custom_price_input=None,
        )
        assert estimate is None

    def test_custom_provider_with_price_is_priced(self):
        estimate = estimate_unit_cost(
            call_type="image",
            provider_id="custom-3",
            model_id="some-model",
            custom_price_input=0.5,
            custom_price_output=0.0,
            custom_currency="USD",
        )
        assert estimate is not None
        assert estimate.amount == 0.5
        assert estimate.currency == "USD"

    def test_custom_provider_image_count_multiplies(self):
        estimate = estimate_unit_cost(
            call_type="image",
            provider_id="custom-3",
            model_id="some-model",
            custom_price_input=0.5,
            custom_price_output=0.0,
            custom_currency="USD",
            image_count=3,
        )
        assert estimate is not None
        assert estimate.amount == 1.5

    def test_audio_character_count_prices_via_usage_tokens(self):
        estimate = estimate_unit_cost(
            call_type="audio",
            provider_id="custom-7",
            model_id="tts-model",
            character_count=20_000,
            custom_price_input=1.0,
            custom_price_output=0.0,
            custom_currency="USD",
        )
        assert estimate is not None
        assert estimate.amount == 2.0  # 20_000 字符 / 万字符单位 × 1.0


class TestAggregateCostEstimate:
    def test_all_priced_same_currency_sums_and_gates_ok(self):
        units = {
            "u1": UnitCostEstimate(amount=1.0, currency="USD", provider_id="p", model_id="m"),
            "u2": UnitCostEstimate(amount=2.0, currency="USD", provider_id="p", model_id="m"),
        }
        payload = aggregate_cost_estimate(units, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["total"] == {"amount": 3.0, "currency": "USD"}
        assert payload["threshold"] == "ok"
        assert payload["unpriced_units"] == []

    def test_crossing_soft_threshold_warns(self):
        units = {"u1": {"amount": 6.0, "currency": "USD"}}
        payload = aggregate_cost_estimate(units, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["threshold"] == "warn"

    def test_crossing_hard_threshold_requires_confirm(self):
        units = {"u1": {"amount": 25.0, "currency": "USD"}}
        payload = aggregate_cost_estimate(units, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["threshold"] == "confirm"

    def test_unpriced_unit_excluded_from_total_and_listed(self):
        units = {
            "u1": {"amount": 1.0, "currency": "USD"},
            "u2": None,
        }
        payload = aggregate_cost_estimate(units, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["total"] == {"amount": 1.0, "currency": "USD"}
        assert payload["unpriced_units"] == ["u2"]

    def test_mixed_currency_has_no_total_and_falls_back_ok(self):
        units = {
            "u1": {"amount": 100.0, "currency": "USD"},
            "u2": {"amount": 100.0, "currency": "CNY"},
        }
        payload = aggregate_cost_estimate(units, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["total"] is None
        assert payload["threshold"] == "ok"

    def test_all_unpriced_has_no_total(self):
        payload = aggregate_cost_estimate({"u1": None}, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["total"] is None
        assert payload["units"] == {}
        assert payload["unpriced_units"] == ["u1"]

    def test_non_usd_total_never_gates(self):
        units = {"u1": {"amount": 1000.0, "currency": "CNY"}}
        payload = aggregate_cost_estimate(units, soft_threshold_usd=5.0, hard_threshold_usd=20.0)
        assert payload["threshold"] == "ok"
