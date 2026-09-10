"""分镜视频（图生视频路径）请求时长档位的单一真相源。

型号声明的 ``supported_durations`` 是全集，执行期真正合法的档位还要按「分辨率↔时长」联动
约束收窄（:func:`lib.config.resolver.constrain_durations`）。入队前的准入预检与 worker 执行
必须用**同一个分辨率口径**收窄，否则两边会为同一条剧本时长取到不同档位：预检要求用户确认
一档、执行却按另一档申请。

分镜视频路径下发给供应商的分辨率是 ``resolve_resolution()`` 的原始结果——``None`` 即不传该
参数、由供应商按自己的默认档位处理——收窄按这个值求值，不补供应商兜底档位（那是参考生视频
路径的口径，见 :func:`lib.reference_video.request_projection.strict_reference_durations`）；
也不施加参考图约束，分镜视频不走参考图端点。交集为空返回空元组，由调用方 fail loud，
不回退到未收窄的全集。

纯函数，无 I/O。
"""

from __future__ import annotations

from collections.abc import Sequence

from lib.config.resolver import constrain_durations


def storyboard_video_duration_tiers(
    provider_id: str | None,
    model_id: str | None,
    supported_durations: Sequence[int],
    *,
    resolution: str | None,
) -> tuple[int, ...]:
    """分镜视频在 ``resolution`` 下可申请的时长档位，升序去重。

    ``resolution`` 必须是执行期真正下发给供应商的值（``None`` = 不传，不按分辨率收窄）。
    ``supported_durations`` 里的布尔值与非正数被丢弃。
    """
    normalized = sorted({int(d) for d in supported_durations if not isinstance(d, bool) and d > 0})
    if not normalized:
        return ()
    return tuple(
        constrain_durations(
            provider_id,
            model_id,
            normalized,
            resolution=resolution,
            uses_reference_images=False,
            fallback_on_empty=False,
        )
    )


__all__ = ["storyboard_video_duration_tiers"]
