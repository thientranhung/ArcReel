"""目标受众（``audience``）字段的单一真相源：字段名、读时解析、观众文案兜底。

项目级可选设置，落在 ``project.json`` 顶层，字符串、无固定枚举（如「儿童 6-10 岁」
「成人」）。只读、无 UI 入口、无写入侧校验——创建 / PATCH 请求模型不收录该字段，
存量项目缺此键时按「未设」处理，无需迁移（``lib/project_migrations`` 的迁移步只处理
「旧代码写出的、与当前代码期望不同的数据」；缺键不是这种旧形态，读时按 ``None`` 兜底即可）。

``resolve_project_audience_text`` 是提示词层用来判定「面向儿童」的唯一入口：显式字段优先，
缺失时退回 overview 的 ``world_setting`` / ``theme`` 文本——已有项目（如 Bible story 示例项目）
把受众写在 overview 里而非专用字段，靠这条兜底同样受益，不必先手改 project.json。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: 目标受众在 ``project.json`` 的顶层字段名。
PROJECT_AUDIENCE_FIELD: str = "audience"


def project_audience(project: Mapping[str, Any] | None) -> str | None:
    """从 project.json 读取显式 ``audience`` 字段，缺失 / 非字符串 / 空白一律返回 ``None``。"""
    if not isinstance(project, Mapping):
        return None
    raw = project.get(PROJECT_AUDIENCE_FIELD)
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def resolve_project_audience_text(project: Mapping[str, Any] | None) -> str | None:
    """解析用于受众 gear 判定的文本：显式 ``audience`` 字段优先，否则退回 overview 文本。

    退回文本取 ``overview.world_setting`` 与 ``overview.theme`` 拼接——两者是项目概述里
    最可能写下「面向儿童」「6-10 岁」这类受众线索的字段。两者皆空时返回 ``None``，
    调用方（``render_audience_section``）据此不渲染任何 gear 规则块。
    """
    explicit = project_audience(project)
    if explicit is not None:
        return explicit
    if not isinstance(project, Mapping):
        return None
    overview = project.get("overview")
    overview = overview if isinstance(overview, Mapping) else {}
    parts = [
        text
        for text in (overview.get("world_setting"), overview.get("theme"))
        if isinstance(text, str) and text.strip()
    ]
    return "\n".join(parts) if parts else None


__all__ = [
    "PROJECT_AUDIENCE_FIELD",
    "project_audience",
    "resolve_project_audience_text",
]
