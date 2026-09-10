"""``lib.generation_worker._encode_task_failure_message``：异常 → 落库的结构化 error_message。

拆自 ``test_generation_worker_module.py``（3000 行熔断，见 CONTRIBUTING.md「测试选择」），
与该文件同一个被测模块，只是聚焦失败编码这一个行为域。
"""

from __future__ import annotations

from typing import Any

import httpx

from lib.generation_worker import _encode_task_failure_message
from lib.http_status_errors import ProviderRejectedError
from lib.task_failure import parse_failure
from lib.video_backends.base import ProviderGenerationFailedError


def _rejected_error(*, provider_reason: str | None, provider_code: str | None) -> ProviderRejectedError:
    request = httpx.Request("POST", "https://x/v2")
    response = httpx.Response(400, request=request)
    return ProviderRejectedError(
        "400 response for https://x/v2",
        request=request,
        response=response,
        provider_reason=provider_reason,
        provider_code=provider_code,
    )


def _parsed(stored: str) -> tuple[str, dict[str, Any]]:
    parsed = parse_failure(stored)
    assert parsed is not None
    return parsed


class TestEncodeTaskFailureMessage:
    """``_encode_task_failure_message``：纯函数，异常 → 落库的结构化 error_message。"""

    def test_provider_rejected_without_structured_code_has_no_moderation_category(self):
        # 拒因摘要非空但没有可分类的结构化码（如 "InvalidParameter"）：不落 moderation_category。
        exc = _rejected_error(provider_reason="InvalidParameter: bad prompt", provider_code="InvalidParameter")
        stored = _encode_task_failure_message(exc)
        code, params = _parsed(stored)
        assert code == "provider_rejected"
        assert "moderation_category" not in params

    def test_provider_rejected_with_openai_content_policy_code_carries_moderation_category(self):
        exc = _rejected_error(provider_reason="content policy violation", provider_code="content_policy_violation")
        stored = _encode_task_failure_message(exc)
        code, params = _parsed(stored)
        assert code == "provider_rejected"
        assert params["moderation_category"] == "sensitive_text"

    def test_provider_generation_failed_encodes_status_code_and_message(self):
        exc = ProviderGenerationFailedError(
            provider="ark",
            label="Ark",
            status="failed",
            provider_code="OutputVideoSensitiveContentDetected",
            provider_message="output flagged",
        )
        stored = _encode_task_failure_message(exc)
        code, params = _parsed(stored)
        assert code == "provider_generation_failed"
        assert params == {
            "status": "failed",
            "provider_message": "output flagged",
            "provider_code": "OutputVideoSensitiveContentDetected",
            "moderation_category": "sensitive_output",
        }

    def test_provider_generation_failed_without_code_omits_optional_params(self):
        exc = ProviderGenerationFailedError(
            provider="ark", label="Ark", status="failed", provider_code=None, provider_message="Unknown error"
        )
        stored = _encode_task_failure_message(exc)
        code, params = _parsed(stored)
        assert code == "provider_generation_failed"
        assert params == {"status": "failed", "provider_message": "Unknown error"}
