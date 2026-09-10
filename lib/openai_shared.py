"""
OpenAI 共享工具模块

供 text_backends / image_backends / video_backends / providers 复用。

包含：
- OPENAI_RETRYABLE_ERRORS — 幂等调用（轮询 / 下载）可重试错误类型
- OPENAI_SUBMIT_RETRYABLE_ERRORS — 非幂等「创建 + 计费」调用（Sora 视频 / gpt-image 图片）
  可重试错误类型，不含 APIConnectionError/APITimeoutError（见 should_retry_openai_submit）
- should_retry_openai_submit — 配套 OPENAI_SUBMIT_RETRYABLE_ERRORS 的 retry_if 谓词
- create_openai_client — AsyncOpenAI 客户端工厂
- OPENAI_IMAGE_QUALITY_MAP — image_size 档位 → quality 映射，供 image_backends.openai 消费。
  尺寸不再用静态 (image_size, aspect_ratio) → "WxH" 表，改由 lib.aspect_size 按比例精确计算
  （比例优先、清晰度其次），见 docs/adr/0011。
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from lib.config.url_utils import OFFICIAL_OPENAI_BASE_URL

logger = logging.getLogger(__name__)

OPENAI_RETRYABLE_ERRORS: tuple[type[Exception], ...] = ()

# 非幂等「创建 + 计费」调用（Sora videos.create / gpt-image images.generate/edit）专用可重试
# 集合：故意不含 APIConnectionError（及其子类 APITimeoutError）。openai SDK 的
# _base_client._request 把 httpx.TimeoutException（ConnectTimeout 与 ReadTimeout 同归一类）
# 一律包成 APITimeoutError，把其余传输异常（含请求已发出后的连接中断）一律包成
# APIConnectionError——SDK 不透传底层 httpx 异常类型，无法像 submit_post 那样区分「连接建立
# 失败（确定未送达）」与「发出后超时/中断（可能已送达并计费）」，故两者一律不重试，按歧义态
# 终态失败处理（调用方捕获后转 AmbiguousSubmitError）。只有服务端已明确响应的
# InternalServerError（5xx）/ RateLimitError（429）才重试。
OPENAI_SUBMIT_RETRYABLE_ERRORS: tuple[type[Exception], ...] = ()

OPENAI_IMAGE_QUALITY_MAP: dict[str, str] = {
    "512px": "low",
    "1K": "medium",
    "2K": "high",
    "4K": "high",
}

try:
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    OPENAI_RETRYABLE_ERRORS = (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )
    OPENAI_SUBMIT_RETRYABLE_ERRORS = (
        InternalServerError,
        RateLimitError,
    )
except ImportError:
    pass  # openai 是必装依赖，此分支仅作防御性保护；回退到空 tuple


def should_retry_openai_submit(exc: Exception) -> bool:
    """非幂等「创建 + 计费」调用重试谓词，配套 ``OPENAI_SUBMIT_RETRYABLE_ERRORS`` 使用。

    传给 ``with_retry_async(retry_if=...)`` 以绕开默认的字符串模式匹配兜底——
    ``APIConnectionError``/``APITimeoutError`` 的 message 文本常含 "timeout"/"500" 等
    子串，字符串兜底会把本应终态失败的歧义态误判为可重试。只信 isinstance 判定。
    """
    return isinstance(exc, OPENAI_SUBMIT_RETRYABLE_ERRORS)


def create_openai_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    max_retries: int | None = None,
) -> AsyncOpenAI:
    """创建 AsyncOpenAI 客户端，统一处理 api_key 和 base_url。

    base_url 为空（None/空白）时显式回填官方端点：AsyncOpenAI 对空 base_url
    会回落读取 OPENAI_BASE_URL 环境变量，环境残留将静默覆盖 DB 配置。base_url
    的唯一来源是 DB，此处兜死显式值断掉该回落路径。
    """
    kwargs: dict = {"base_url": (base_url or "").strip() or OFFICIAL_OPENAI_BASE_URL}
    if api_key:
        kwargs["api_key"] = api_key
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return AsyncOpenAI(**kwargs)
