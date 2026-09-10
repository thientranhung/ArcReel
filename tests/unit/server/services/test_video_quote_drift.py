"""``_video_quote_drift_warning``：留痕报价与执行期实际解析值的漂移比对（Commit 2）。"""

from __future__ import annotations

from server.services.generation_tasks import VIDEO_QUOTE_DRIFT_WARNING, _video_quote_drift_warning


def _live(**overrides):
    base = {
        "live_provider_id": "ark",
        "live_model_id": "doubao-seedance-2-0-mini-260615",
        "live_resolution": "720p",
        "live_duration_seconds": 8,
    }
    base.update(overrides)
    return base


def test_no_stored_quote_never_warns():
    assert _video_quote_drift_warning({}, **_live()) is None
    assert _video_quote_drift_warning({"quote": "not-a-dict"}, **_live()) is None


def test_matching_quote_does_not_warn():
    payload = {
        "quote": {
            "provider_id": "ark",
            "model_id": "doubao-seedance-2-0-mini-260615",
            "duration_seconds": 8,
            "amount": 0.55,
            "currency": "USD",
        }
    }
    assert _video_quote_drift_warning(payload, **_live()) is None


def test_provider_drift_warns_with_both_values():
    payload = {"quote": {"provider_id": "gemini-aistudio", "model_id": None, "duration_seconds": None}}

    warning = _video_quote_drift_warning(payload, **_live())

    assert warning is not None
    assert warning["key"] == VIDEO_QUOTE_DRIFT_WARNING
    assert warning["params"]["mismatches"]["provider_id"] == {"quoted": "gemini-aistudio", "live": "ark"}
    assert "model_id" not in warning["params"]["mismatches"]


def test_model_and_duration_drift_both_reported():
    payload = {
        "quote": {
            "provider_id": "ark",
            "model_id": "doubao-seedance-2-5-260628",
            "duration_seconds": 4,
        }
    }

    warning = _video_quote_drift_warning(payload, **_live())

    assert warning is not None
    mismatches = warning["params"]["mismatches"]
    assert mismatches["model_id"] == {"quoted": "doubao-seedance-2-5-260628", "live": "doubao-seedance-2-0-mini-260615"}
    assert mismatches["duration_seconds"] == {"quoted": 4, "live": 8}
    assert "provider_id" not in mismatches


def test_never_raises_and_never_overrides_live_values():
    """ADR 0061：这条 warning 只是留痕对照，绝不改变已经解析出的执行期身份。"""

    payload = {"quote": {"provider_id": "custom-9"}}
    live = _live()

    warning = _video_quote_drift_warning(payload, **live)

    assert warning is not None
    assert live["live_provider_id"] == "ark"  # 未被 warning 计算过程改写
