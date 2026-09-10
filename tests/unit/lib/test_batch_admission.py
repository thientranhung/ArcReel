"""整批准入判定的纯折叠：一批目标的整体结论与逐 unit 转述。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from lib.batch_admission import (
    COST_CONFIRMATION_CODE,
    BatchAdmission,
    BatchAdmissionDecision,
    UnitAdmissionTicket,
    refused_ticket,
)
from lib.generation_result import (
    GenerationAction,
    GenerationProblem,
    GenerationProblemCode,
    GenerationResultBuilder,
    GenerationSelectionMode,
)


def _admission(*tickets: UnitAdmissionTicket, delivery: str = "post_production") -> BatchAdmission:
    return BatchAdmission(
        operation="generate_reference_videos_batch",
        selection=GenerationSelectionMode.MISSING_ONLY,
        narration_delivery=delivery,
        tickets=tickets,
    )


def _confirmation_ticket(
    unit_id: str,
    *,
    request: int,
    current: int | None = None,
    amount: float | None = None,
    currency: str = "USD",
):
    return UnitAdmissionTicket(
        unit_id=unit_id,
        problems=(
            GenerationProblem(
                code="reference_duration_confirmation_required",
                detail="档位与当前视觉不一致",
                action=GenerationAction.CONFIRM_REQUEST_DURATION,
                params={"request_duration": request},
            ),
        ),
        request_duration_seconds=request,
        current_duration_seconds=current,
        request_cost=(
            None if amount is None else {"amount": amount, "currency": currency, "request_duration_seconds": request}
        ),
    )


def test_all_clean_tickets_admit_the_batch():
    admission = _admission(UnitAdmissionTicket(unit_id="E1U1"), UnitAdmissionTicket(unit_id="E1U2"))

    assert admission.decision is BatchAdmissionDecision.ADMITTED
    assert admission.admitted is True
    assert admission.unit_ids == ("E1U1", "E1U2")
    assert admission.refused_tickets == ()


def test_one_problem_refuses_the_whole_batch():
    admission = _admission(
        UnitAdmissionTicket(unit_id="E1U1"),
        refused_ticket(
            "E1U2",
            code=GenerationProblemCode.UNIT_INPUT_UNUSABLE,
            detail="缺分镜图",
            action=GenerationAction.GENERATE_DEPENDENCY,
        ),
    )

    assert admission.decision is BatchAdmissionDecision.BLOCKED
    assert admission.admitted is False


def test_consent_only_problems_are_not_blockers():
    admission = _admission(UnitAdmissionTicket(unit_id="E1U1"), _confirmation_ticket("E1U2", request=8))

    assert admission.decision is BatchAdmissionDecision.CONFIRMATION_REQUIRED


def test_a_real_blocker_outranks_pending_consent():
    """确认与受阻同时存在时按受阻处理：先修缺口，再谈档位。"""

    admission = _admission(
        _confirmation_ticket("E1U1", request=8),
        refused_ticket(
            "E1U2",
            code=GenerationProblemCode.ACTIVE_TASK_CONFLICT,
            detail="已有在途任务",
            action=GenerationAction.WAIT_FOR_TASK,
        ),
    )

    assert admission.decision is BatchAdmissionDecision.BLOCKED


def _cost_confirmation_ticket(unit_id: str, *, amount: float, currency: str = "USD") -> UnitAdmissionTicket:
    return UnitAdmissionTicket(
        unit_id=unit_id,
        problems=(
            GenerationProblem(
                code=COST_CONFIRMATION_CODE,
                detail="预估费用超过项目费用阈值",
                action=GenerationAction.CONFIRM_REQUEST_DURATION,
                params={},
            ),
        ),
        request_cost={"amount": amount, "currency": currency},
    )


def test_cost_confirmation_is_consent_only():
    """单独的费用阈值确认与档位确认走同一条 consent-only 路径，不当作受阻。"""

    admission = _admission(UnitAdmissionTicket(unit_id="E1U1"), _cost_confirmation_ticket("E1U2", amount=25.0))

    assert admission.decision is BatchAdmissionDecision.CONFIRMATION_REQUIRED


def test_cost_confirmation_folds_into_confirmation_tiers():
    admission = _admission(_cost_confirmation_ticket("E1U1", amount=25.0))

    tiers = admission.confirmation_tiers()

    assert len(tiers) == 1
    assert tiers[0].unit_ids == ("E1U1",)
    assert tiers[0].cost_amount == pytest.approx(25.0)
    assert tiers[0].cost_currency == "USD"


def test_duration_and_cost_confirmation_on_the_same_ticket_is_still_consent_only():
    """同一票既要确认档位又要确认费用，仍属可由用户一次同意清空的口子，不升级为受阻。"""

    ticket = UnitAdmissionTicket(
        unit_id="E1U1",
        problems=(
            GenerationProblem(
                code="reference_duration_confirmation_required",
                detail="档位与当前视觉不一致",
                action=GenerationAction.CONFIRM_REQUEST_DURATION,
                params={},
            ),
            GenerationProblem(
                code=COST_CONFIRMATION_CODE,
                detail="预估费用超过项目费用阈值",
                action=GenerationAction.CONFIRM_REQUEST_DURATION,
                params={},
            ),
        ),
        request_cost={"amount": 25.0, "currency": "USD"},
    )
    admission = _admission(ticket)

    assert admission.decision is BatchAdmissionDecision.CONFIRMATION_REQUIRED
    assert admission.confirmation_tiers()[0].cost_amount == pytest.approx(25.0)


def test_confirmation_tiers_group_by_request_duration_with_totals():
    admission = _admission(
        _confirmation_ticket("E1U1", request=8, amount=0.8),
        _confirmation_ticket("E1U2", request=8, amount=0.8),
        _confirmation_ticket("E1U3", request=12, amount=1.2),
        UnitAdmissionTicket(unit_id="E1U4"),
    )

    tiers = admission.confirmation_tiers()

    assert [(tier.request_duration_seconds, tier.unit_count, tier.cost_amount) for tier in tiers] == [
        (8, 2, pytest.approx(1.6)),
        (12, 1, pytest.approx(1.2)),
    ]
    assert tiers[0].unit_ids == ("E1U1", "E1U2")
    assert tiers[0].cost_currency == "USD"


def test_a_tier_with_an_unquoted_member_reports_no_total():
    """报价不全的档位不给合计：部分求和会低报用户正在同意支付的金额。"""

    admission = _admission(
        _confirmation_ticket("E1U1", request=8, amount=0.8),
        _confirmation_ticket("E1U2", request=8),
    )

    tier = admission.confirmation_tiers()[0]

    assert tier.unit_count == 2
    assert tier.cost_amount is None


def test_a_tier_quoted_in_two_currencies_reports_no_total():
    """币种不一的报价加不出一个数：合计与币种一起留空，不给出无从解读的金额。"""

    admission = _admission(
        _confirmation_ticket("E1U1", request=8, amount=1.0, currency="USD"),
        _confirmation_ticket("E1U2", request=8, amount=7.0, currency="CNY"),
    )

    tier = admission.confirmation_tiers()[0]

    assert tier.unit_count == 2
    assert tier.cost_amount is None
    assert tier.cost_currency is None


def test_refusal_reports_every_requested_unit_including_the_clean_ones():
    admission = _admission(
        UnitAdmissionTicket(unit_id="E1U1"),
        refused_ticket(
            "E1U2",
            code=GenerationProblemCode.UNIT_INPUT_UNUSABLE,
            detail="缺分镜图",
            action=GenerationAction.GENERATE_DEPENDENCY,
        ),
    )
    builder = GenerationResultBuilder("generate_reference_videos_batch", GenerationSelectionMode.MISSING_ONLY)

    admission.record_refusal(builder)
    result = builder.build()

    assert sorted(result.blocked) == ["E1U1", "E1U2"]
    assert result.succeeded == []
    assert result.failed == []
    problems = {item.unit_id: item.problem for item in result.items if item.problem is not None}
    assert problems["E1U2"].code == GenerationProblemCode.UNIT_INPUT_UNUSABLE
    withheld = problems["E1U1"]
    assert withheld.code == GenerationProblemCode.BATCH_ADMISSION_WITHHELD
    assert withheld.action is GenerationAction.RETRY
    # 被连带扣下的 unit 直接知道该去修谁，不必反查整份清单。
    assert withheld.params["blocked_unit_ids"] == ["E1U2"]


def test_a_unit_with_several_problems_keeps_all_of_them():
    admission = _admission(
        UnitAdmissionTicket(
            unit_id="E1U1",
            problems=(
                GenerationProblem(
                    code="reference_duration_confirmation_required",
                    detail="档位变化",
                    action=GenerationAction.CONFIRM_REQUEST_DURATION,
                ),
                GenerationProblem(
                    code="video_request_cost_unavailable",
                    detail="取不到报价",
                    action=GenerationAction.RETRY,
                ),
            ),
        )
    )
    builder = GenerationResultBuilder("generate_reference_videos_batch", GenerationSelectionMode.EXPLICIT)

    admission.record_refusal(builder)
    item = builder.build().items[0]

    assert item.problem is not None
    assert item.problem.code == "reference_duration_confirmation_required"
    assert [problem["code"] for problem in item.problem.params["problems"]] == [
        "reference_duration_confirmation_required",
        "video_request_cost_unavailable",
    ]


def test_recording_a_refusal_on_an_admitted_batch_is_a_programming_error():
    admission = _admission(UnitAdmissionTicket(unit_id="E1U1"))
    builder = GenerationResultBuilder("generate_reference_videos_batch", GenerationSelectionMode.EXPLICIT)

    with pytest.raises(ValueError, match=r"record_refusal requires a refused admission"):
        admission.record_refusal(builder)


def test_payload_carries_the_decision_every_unit_and_the_tiers():
    admission = _admission(
        _confirmation_ticket("E1U1", request=8, current=4, amount=0.8),
        UnitAdmissionTicket(unit_id="E1U2"),
    )

    payload = admission.to_payload()
    units = cast(list[dict[str, Any]], payload["units"])
    confirmation = cast(dict[str, Any], payload["confirmation"])

    assert payload["decision"] == "confirmation_required"
    assert payload["narration_delivery"] == "post_production"
    assert [unit["unit_id"] for unit in units] == ["E1U1", "E1U2"]
    assert units[0]["admitted"] is False
    assert units[0]["current_duration_seconds"] == 4
    assert units[1]["admitted"] is True
    assert units[1]["withheld"] is True
    assert units[1]["problems"][0]["code"] == "generation_batch_admission_withheld"
    assert confirmation["tiers"][0]["unit_ids"] == ["E1U1"]


def test_payload_omits_confirmation_when_nothing_awaits_consent():
    assert _admission(UnitAdmissionTicket(unit_id="E1U1")).to_payload()["confirmation"] is None
