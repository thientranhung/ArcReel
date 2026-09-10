"""``_stamp_quote_payload``：把整批准入的报价原样留痕进 spec.payload['quote']（Commit 2）。"""

from __future__ import annotations

from lib.batch_admission import BatchAdmission, UnitAdmissionTicket
from lib.generation_queue_client import TaskSpec
from lib.generation_result import GenerationSelectionMode
from server.media_tools.videos import _stamp_quote_payload


def _admission(*tickets: UnitAdmissionTicket) -> BatchAdmission:
    return BatchAdmission(
        operation="generate_videos",
        selection=GenerationSelectionMode.MISSING_ONLY,
        narration_delivery="post_production",
        tickets=tickets,
    )


def test_stamps_quote_fields_onto_the_matching_spec():
    admission = _admission(
        UnitAdmissionTicket(
            unit_id="E1S01",
            request_cost={
                "amount": 0.55,
                "currency": "USD",
                "provider_id": "ark",
                "model_id": "doubao-seedance-2-0-mini-260615",
                "request_duration_seconds": 8,
            },
        )
    )
    spec = TaskSpec.from_request(task_type="video", media_type="video", resource_id="E1S01", prompt="p")

    _stamp_quote_payload([spec], admission)

    assert spec.payload is not None
    assert spec.payload["quote"] == {
        "provider_id": "ark",
        "model_id": "doubao-seedance-2-0-mini-260615",
        "duration_seconds": 8,
        "amount": 0.55,
        "currency": "USD",
    }


def test_unpriced_unit_is_left_untouched():
    admission = _admission(UnitAdmissionTicket(unit_id="E1S01"))
    spec = TaskSpec.from_request(task_type="video", media_type="video", resource_id="E1S01", prompt="p")

    _stamp_quote_payload([spec], admission)

    assert spec.payload is None or "quote" not in spec.payload


def test_existing_payload_keys_are_preserved():
    admission = _admission(
        UnitAdmissionTicket(unit_id="E1S01", request_cost={"amount": 1.0, "currency": "USD"}),
    )
    spec = TaskSpec.from_request(task_type="video", media_type="video", resource_id="E1S01", prompt="p")
    spec.payload = {"reference_request_options": {"foo": "bar"}}

    _stamp_quote_payload([spec], admission)

    assert spec.payload["reference_request_options"] == {"foo": "bar"}
    assert spec.payload["quote"]["amount"] == 1.0
