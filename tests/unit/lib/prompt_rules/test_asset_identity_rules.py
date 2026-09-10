"""``render_asset_identity_rules`` 按 profile 目录交回身份锚定规则正文，测试不抄文案措辞。"""

from pathlib import Path

import pytest

from lib.prompt_rules.asset_identity_rules import (
    ASSET_IDENTITY_RULES_FILE,
    render_asset_identity_rules,
)


def test_rules_come_from_the_profile_directory_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """规则正文住在 agent profile 里，换 profile 目录即换文本——不在导入时定死。"""
    references = tmp_path / ".claude" / "references"
    references.mkdir(parents=True)
    (references / ASSET_IDENTITY_RULES_FILE).write_text("替身身份锚定规则", encoding="utf-8")
    monkeypatch.setenv("ARCREEL_PROFILE_DIR", str(tmp_path))

    assert render_asset_identity_rules() == "替身身份锚定规则"


class TestRepoRuleContent:
    """针对仓库里真实的规则正文断言锚点要求与禁止清单确实存在。"""

    def test_character_identity_anchors_are_mandatory(self) -> None:
        text = render_asset_identity_rules()
        assert "肤色" in text
        assert "发色" in text
        assert "瞳色" in text
        assert "鞋履必须写" in text

    def test_character_forbidden_list(self) -> None:
        text = render_asset_identity_rules()
        assert "表情" in text
        assert "姿势" in text
        assert "动作" in text
        assert "背景/环境" in text
        assert "含糊词" in text
        assert "抽象的非视觉形容词" in text

    def test_character_non_human_and_state_change_guidance(self) -> None:
        text = render_asset_identity_rules()
        assert "非人类角色" in text
        assert "状态变化不是改写本体描述" in text
        assert "衍生" in text

    def test_scene_spatial_anchors(self) -> None:
        text = render_asset_identity_rules()
        assert "3 个稳定的空间锚点" in text
        assert "标签、箭头或占位符" in text

    def test_prop_static_visual_only(self) -> None:
        text = render_asset_identity_rules()
        assert "只写道具本体的静态视觉信息" in text
        assert "不写用途、剧情" in text
