"""分镜-视频的 shot-to-shot 连续性与运镜规则（prompt_authoring 阶段的写作口径）。

移植自 ``docs/research/learn-from-waoowaoo-2026-09-10.md`` §1.3：每分镜内部状态表
（entry state = 上一分镜 exit state + 本分镜新变化，状态只进不退）、参考图只锁定身份
（不继承定妆照的正面居中构图/中性姿态/直视镜头）、表演纪律（禁情绪形容词、低幅度、分层
反应、每分镜至多一次情绪转折）、运镜（单一叙事职能、同时空直切）、视频提示词里的台词与
声音口径（说话人须在场、台词说得完、只写当下能听到的声音、不写 BGM）。

规则正文存放在 ``agent_runtime_profile/.claude/references/shot-continuity-rules.md``，经
:func:`lib.agent_profile.read_profile_reference` 读入：那里既是 drama / narration / 参考生视频
三条 prompt_authoring 共同的参考文档位置，也是本模块的读取来源，仓库里只有一份文本。
"""

from __future__ import annotations

from lib.agent_profile import read_profile_reference

#: `.claude/references/` 下承载规则正文的文件名。
SHOT_CONTINUITY_RULES_FILE = "shot-continuity-rules.md"


def render_shot_continuity_rules() -> str:
    """读取分镜-视频 shot-to-shot 连续性与运镜规则正文。"""
    return read_profile_reference(SHOT_CONTINUITY_RULES_FILE)


__all__ = [
    "SHOT_CONTINUITY_RULES_FILE",
    "render_shot_continuity_rules",
]
