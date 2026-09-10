"""``classify_provider_rejection``：只信结构化 provider 码，不看自然语言原文（ADR 0052）。"""

from __future__ import annotations

import httpx
import pytest

from lib.http_status_errors import ProviderRejectedError
from lib.moderation_rewrite import ModerationCategory, classify_provider_rejection
from lib.video_backends.base import ProviderGenerationFailedError


def _rejected(*, provider_code: str | None, provider_reason: str | None = None) -> ProviderRejectedError:
    request = httpx.Request("POST", "https://x/v2")
    response = httpx.Response(400, request=request)
    return ProviderRejectedError(
        "400 response for https://x/v2",
        request=request,
        response=response,
        provider_reason=provider_reason,
        provider_code=provider_code,
    )


def _generation_failed(*, provider_code: str | None, provider_message: str = "boom") -> ProviderGenerationFailedError:
    return ProviderGenerationFailedError(
        provider="ark", label="Ark", status="failed", provider_code=provider_code, provider_message=provider_message
    )


class _FakeOpenAIError(Exception):
    """按 openai SDK ``APIError`` 的形态挂 ``code`` 属性，不引入真实 SDK 依赖。"""

    def __init__(self, *, code: str | None, message: str) -> None:
        super().__init__(message)
        self.code = code


class TestClassifyProviderRejectionKnownCodes:
    @pytest.mark.parametrize(
        "code",
        ["InputTextSensitiveContentDetected"],
    )
    def test_ark_input_text_sensitive(self, code: str):
        assert classify_provider_rejection(_rejected(provider_code=code)) == ModerationCategory.SENSITIVE_TEXT

    @pytest.mark.parametrize(
        "code",
        ["OutputVideoSensitiveContentDetected", "OutputImageSensitiveContentDetected"],
    )
    def test_ark_output_sensitive(self, code: str):
        assert (
            classify_provider_rejection(_generation_failed(provider_code=code)) == ModerationCategory.SENSITIVE_OUTPUT
        )

    @pytest.mark.parametrize("code", ["content_policy_violation", "moderation_blocked", "content_filter"])
    def test_openai_content_policy_codes(self, code: str):
        assert classify_provider_rejection(_rejected(provider_code=code)) == ModerationCategory.SENSITIVE_TEXT

    def test_openai_sdk_style_exception_reads_code_attribute_directly(self):
        # openai.BadRequestError 之类不是本仓库的 ProviderRejectedError，也没有 provider_code
        # 属性；SDK 把错误体的 code 字段原样挂在 exc.code 上，分类按属性名兜底取它。
        exc = _FakeOpenAIError(code="moderation_blocked", message="blocked")
        assert classify_provider_rejection(exc) == ModerationCategory.SENSITIVE_TEXT


class TestClassifyProviderRejectionUnmatched:
    def test_unrecognized_code_returns_none(self):
        assert classify_provider_rejection(_rejected(provider_code="InvalidParameter")) is None

    def test_missing_code_returns_none(self):
        assert classify_provider_rejection(_rejected(provider_code=None, provider_reason="content violation")) is None

    def test_generation_failed_without_code_returns_none(self):
        assert classify_provider_rejection(_generation_failed(provider_code=None)) is None

    def test_generic_exception_without_code_attribute_returns_none(self):
        assert classify_provider_rejection(RuntimeError("boom")) is None

    def test_does_not_infer_from_message_text(self):
        # provider_reason 里出现已知码的文本形态，但没有结构化 provider_code：不能分类。
        exc = _rejected(provider_code=None, provider_reason="InputTextSensitiveContentDetected: bad prompt")
        assert classify_provider_rejection(exc) is None

    def test_copyright_audio_has_no_known_code_yet(self):
        # 音频版权拦截目前没有已知结构化码（见 lib.moderation_rewrite 顶部注释），任何码都不会
        # 命中 COPYRIGHT_AUDIO——这条测试锁住「没有先例前不得从消息猜测」这一不变量。
        assert classify_provider_rejection(_rejected(provider_code="AudioCopyrightDetected")) is None


def test_unknown_category_is_reserved_and_never_produced():
    """``ModerationCategory.UNKNOWN`` 存在于枚举里，但分类器本身永不产出它。"""
    codes = ["InputTextSensitiveContentDetected", "OutputVideoSensitiveContentDetected", "content_policy_violation"]
    produced = {classify_provider_rejection(_rejected(provider_code=code)) for code in codes}
    assert ModerationCategory.UNKNOWN not in produced
