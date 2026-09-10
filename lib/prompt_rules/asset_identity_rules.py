"""角色 / 场景 / 道具资产的身份锚定规则（extraction 阶段的 description 写作口径）。

移植自 `docs/research/learn-from-waoowaoo-2026-09-10.md` §1.1-1.2：角色 description 必须写死
肤色/发色/瞳色等身份锚点、禁止表情姿势等易变信息；场景 description 要落成有空间锚点的稳定
空间；道具 description 只写静态视觉信息。

规则正文存放在 ``agent_runtime_profile/.claude/references/asset-identity-rules.md``，经
:func:`lib.agent_profile.read_profile_reference` 读入：那里既是 `analyze-assets` 子智能体
Step 3 写 description 前必读的参考文档位置，也是本模块的读取来源，仓库里只有一份文本。
"""

from __future__ import annotations

from lib.agent_profile import read_profile_reference

#: `.claude/references/` 下承载规则正文的文件名。
ASSET_IDENTITY_RULES_FILE = "asset-identity-rules.md"


def render_asset_identity_rules() -> str:
    """读取角色 / 场景 / 道具 description 的身份锚定规则正文。"""
    return read_profile_reference(ASSET_IDENTITY_RULES_FILE)


__all__ = [
    "ASSET_IDENTITY_RULES_FILE",
    "render_asset_identity_rules",
]
