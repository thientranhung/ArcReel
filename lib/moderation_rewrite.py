"""供应商拒绝/生成失败 → 审核类别的纯分类（不改行为，不发起重写）。

ADR 0052（保留证据而非从自然语言原文倒推根因）在这里的落点：分类只信结构化字段
——``ProviderRejectedError.provider_code`` / ``ProviderGenerationFailedError.provider_code``
/ 上游 SDK 异常自带的 ``code`` 属性——绝不对 ``provider_reason`` / ``provider_message`` /
``str(exc)`` 这类自然语言原文做正则或子串匹配。原文本身仍完整保留在失败信封里，供人工排查，
只是不参与分类判定。

本模块只做分类，不做改写/重试决策；是否据分类发起改写在别的 PR（见调用方 issue）。
"""

from __future__ import annotations

from enum import StrEnum

from lib.http_status_errors import ProviderRejectedError
from lib.video_backends.base import ProviderGenerationFailedError


class ModerationCategory(StrEnum):
    """已知的审核拒绝类别，均只能通过结构化 provider 码判定。

    没有 ``nudity``：现有供应商的结构化码里没有一条能单独指向「色情/裸露」——OpenAI 的
    ``content_policy_violation`` / ``moderation_blocked`` 覆盖整个内容策略大类，细分原因
    只在自然语言 message 里，而分类不信 message。落地时一律归 ``SENSITIVE_TEXT``。
    """

    SENSITIVE_TEXT = "sensitive_text"
    """输入侧（prompt/脚本文本）被判定触发内容安全策略。"""
    SENSITIVE_OUTPUT = "sensitive_output"
    """已生成内容（图片/视频）本身被判定触发内容安全策略。"""
    COPYRIGHT_AUDIO = "copyright_audio"
    """音频侧版权拦截。当前没有任何已知供应商为此暴露结构化码（见下方 ``_ARK_...`` 常量的
    注释），此类别目前不会被 :func:`classify_provider_rejection` 产出，保留在枚举里等结构化
    信号出现后再接线，避免调用方要为「未来才会出现的类别」预留特殊分支。"""
    UNKNOWN = "unknown"
    """占位类别：分类器本身不产出它（未匹配一律返回 ``None``），供下游需要区分「已知是审核
    拒绝但分类未收录该码」与「完全没有可分类信号」两种语义时使用，不在本模块内使用。"""


# Ark：输入文本触发内容安全策略。取自 Ark 官方视频生成 API 错误码文档
# （创建/查询任务错误码表，`ContentGenerationError.code` 字段）。
_ARK_INPUT_TEXT_SENSITIVE_CODES: frozenset[str] = frozenset({"InputTextSensitiveContentDetected"})

# Ark：生成产物（视频/图片）本身触发内容安全策略。
_ARK_OUTPUT_SENSITIVE_CODES: frozenset[str] = frozenset(
    {
        "OutputVideoSensitiveContentDetected",
        "OutputImageSensitiveContentDetected",
    }
)

# Ark 的参考音频版权拦截目前只在文档里以自然语言描述（如「参考音频涉嫌侵权」），没有配套的
# 结构化 error.code——与视觉审核不同，音频版权判定没有独立机器码可取。分类不对自然语言原文
# 匹配（ADR 0052），因此这一类恒返回 None，直到供应商侧补上结构化码。集合留空且不参与
# `_CODE_TO_CATEGORY`，避免有人往这里塞消息子串「顺手」接上。
_ARK_COPYRIGHT_AUDIO_CODES: frozenset[str] = frozenset()

# OpenAI 兼容协议（官方 Sora / gpt-image，及透传同一错误体的中转网关）把内容策略拒绝的机器码
# 放在错误体的 ``code`` 字段——与 lib.call_failure.CONTENT_POLICY_PROVIDER_CODES 同一批码，
# 复用同一常量避免两处分类漂移成两份口径。
_OPENAI_CONTENT_POLICY_CODES: frozenset[str] = frozenset(
    {"content_filter", "content_policy_violation", "moderation_blocked"}
)

_CODE_TO_CATEGORY: dict[str, ModerationCategory] = {
    **dict.fromkeys(_ARK_INPUT_TEXT_SENSITIVE_CODES, ModerationCategory.SENSITIVE_TEXT),
    **dict.fromkeys(_ARK_OUTPUT_SENSITIVE_CODES, ModerationCategory.SENSITIVE_OUTPUT),
    **dict.fromkeys(_OPENAI_CONTENT_POLICY_CODES, ModerationCategory.SENSITIVE_TEXT),
}


def classify_provider_rejection(exc: BaseException) -> ModerationCategory | None:
    """按结构化 provider 码给一次供应商拒绝/生成失败分类；认不出返回 ``None``。

    认不出覆盖两种情况，调用方无需/无法区分：没有任何结构化码可取（响应体为空、认证类
    状态码不透传原文），以及码存在但不在已收录集合里（新供应商码、Ark 尚未见过的分类）。
    两种情况都不该由这里猜测——``None`` 是唯一诚实的返回值，读侧据此保留默认动作而不是
    强行给一个可能错误的分类。
    """
    code = _provider_code(exc)
    if code is None:
        return None
    return _CODE_TO_CATEGORY.get(code)


def _provider_code(exc: BaseException) -> str | None:
    """取异常上的结构化 provider 码，不看消息文本。

    ``ProviderRejectedError`` / ``ProviderGenerationFailedError`` 是本仓库内的结构化类型，
    直接取其 ``provider_code``。其余异常（如 openai SDK 的 ``APIError`` 子类）按属性名兜底
    取 ``code``——该 SDK 把错误体的 ``code`` 字段原样挂到异常实例上，是机器字段而非拼出来的
    消息文本，与 ``lib.call_failure._provider_error_code`` 同一口径。
    """
    if isinstance(exc, ProviderRejectedError | ProviderGenerationFailedError):
        return exc.provider_code
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code.strip() else None
