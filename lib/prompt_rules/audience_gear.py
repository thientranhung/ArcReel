"""目标受众「gear」规则：按受众文本切换创作规则块，目前只实现儿童（约 6-10 岁）档位。

其他同类项目（见 ``docs/research/learn-from-waoowaoo-2026-09-10.md`` §1.4）没有儿童向
创作规则，这是差异化能力，需要自己写好——不是随手翻译几条通用注意事项。

判据：传入的 ``audience`` 文本命中中 / 英 / 越三语的儿童线索词，或命中形如 ``6-10``、
``6–10``、``6 đến 10`` 的年龄区间（数字落在学龄前到少年的合理范围），即判定为儿童受众、
交回儿童 gear 规则块；否则返回空串，调用方不渲染任何受众专属规则——成人 / 未设受众的
prompt 与加这个功能之前逐字相同。

``audience`` 的取值由调用方解析（见 ``lib.project_audience.resolve_project_audience_text``）：
可能是项目显式 ``audience`` 字段，也可能是 overview 的 ``world_setting`` / ``theme`` 文本
兜底——本模块只负责在给定文本里识别儿童线索，不关心文本来自哪个字段。
"""

from __future__ import annotations

import re

#: 儿童 / 少儿关键词：中文、英文、越南语。越南语两个常见说法都收（「trẻ em」泛指儿童，
#: 「thiếu nhi」多用于少儿向内容语境，如「thiếu nhi」节目）。
_KIDS_KEYWORD_PATTERN = re.compile(
    r"儿童|少儿|少年儿童|kids?|children|trẻ\s*em|thiếu\s*nhi",
    re.IGNORECASE,
)

#: 年龄区间线索：形如「6-10」「6–10」「6 đến 10」。分隔符收 ``-`` / ``–`` / ``~`` / ``to`` /
#: 越南语「đến」；数字限制在 3-14，避开与年龄无关的区间（集数、章节号等通常不落在此区间内，
#: 且真正的儿童内容年龄区间也集中在这一段）。
_KIDS_AGE_RANGE_PATTERN = re.compile(
    r"(?<!\d)([3-9]|1[0-4])\s*(?:-|–|~|to|đến)\s*([3-9]|1[0-4])(?!\d)",
    re.IGNORECASE,
)

_KIDS_GEAR_BLOCK = """面向儿童（约 6-10 岁）观众的创作规则：
- 每集只服务一个清晰的问题或愿望，不堆叠多条故事线。
- 因果具体可见（做了什么 → 发生了什么），不用抽象说教或直接讲道理。
- 同屏最多 3 个具名角色，避免认知过载。
- 每种情绪都落在孩子能模仿的具体动作上（跺脚、抱紧、缩肩、蹦跳），不用抽象形容词交代情绪。
- 旁白 / 台词句子简短（每句 ≤12 个词），一句只讲一个意思。
- 全集安排一个重复 / 呼应的记忆点（一句口头禅、一个招牌动作），用且只用一次成体系地回收。
- 禁止 jump-scare、禁止血腥暴力、禁止恋爱线、禁止孩子解不开的讽刺挖苦。
- 危险 / 冲突在本集内解决完，不留到下集才收尾。
- 结尾落在一个温暖具体的收获，再给下一集留一个玩味的好奇心钩子——不是会吓到孩子的悬念。
- 幽默来自肢体喜剧与温和的意外，不靠嘲讽或阴阳怪气。
- 色彩明亮，人物面部在近景时表情清晰可读。"""


def _looks_like_kids_audience(audience: str) -> bool:
    return bool(_KIDS_KEYWORD_PATTERN.search(audience) or _KIDS_AGE_RANGE_PATTERN.search(audience))


def render_audience_section(audience: str | None) -> str:
    """按受众文本渲染受众 gear 规则块；无受众 / 非儿童受众时返回空串。

    空串是有意的空操作信号：调用方（``build_normalize_prompt`` / ``build_drama_prompt``）
    按「truthy 才插入区块」处理，未设受众或成人受众时 prompt 逐字不变。
    """
    if not audience or not audience.strip():
        return ""
    if not _looks_like_kids_audience(audience):
        return ""
    return _KIDS_GEAR_BLOCK


__all__ = ["render_audience_section"]
