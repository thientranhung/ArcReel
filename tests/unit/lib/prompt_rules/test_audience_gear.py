"""``render_audience_section`` 按受众文本判定是否渲染儿童 gear 规则块。"""

import pytest

from lib.prompt_rules.audience_gear import render_audience_section


class TestNoAudience:
    def test_none_returns_empty_string(self):
        assert render_audience_section(None) == ""

    def test_blank_returns_empty_string(self):
        assert render_audience_section("   ") == ""

    def test_empty_string_returns_empty_string(self):
        assert render_audience_section("") == ""


class TestAdultAudience:
    @pytest.mark.parametrize(
        "audience",
        [
            "成人",
            "年轻女性，都市情感",
            "adult audience, workplace drama",
            "18-35 岁都市白领",
        ],
    )
    def test_no_kids_cue_returns_empty_string(self, audience: str):
        assert render_audience_section(audience) == ""


class TestKidsAudienceCueLanguages:
    @pytest.mark.parametrize(
        "audience",
        [
            "儿童",
            "少儿向内容",
            "面向 6-10 岁儿童",
            "kids",
            "children",
            "for children aged 6-10",
            "trẻ em",
            "dành cho trẻ em",
            "thiếu nhi",
        ],
    )
    def test_keyword_cue_renders_block(self, audience: str):
        block = render_audience_section(audience)
        assert block != ""
        assert "儿童" in block
        assert "6-10" in block

    @pytest.mark.parametrize(
        "audience",
        [
            "6-10 岁",
            "6–10 岁",
            "6 đến 10 tuổi",
            "ages 6-10",
            "age: 6-10",
            "6 to 10 years old",
            "6-10 year-olds",
        ],
    )
    def test_age_range_with_marker_renders_block_without_keyword(self, audience: str):
        block = render_audience_section(audience)
        assert block != ""
        assert "面向儿童" in block


class TestBareAgeRangeWithoutMarker:
    """年龄区间必须紧邻标记词（岁 / tuổi / years / ages 等）才算数：overview 里常见的集数 /
    章节号数字区间（与年龄无关）不该被误判成儿童受众。"""

    @pytest.mark.parametrize(
        "audience",
        [
            "第 3-9 章",
            "tập 6-10",
            "chapters 5-8",
            "6-10 集",
            "第 6-10 回",
        ],
    )
    def test_bare_range_without_age_marker_returns_empty_string(self, audience: str):
        assert render_audience_section(audience) == ""


class TestKidsGearContent:
    def test_block_covers_required_rules(self):
        block = render_audience_section("儿童 6-10 岁")
        for fragment in (
            "一个清晰的问题或愿望",
            "因果具体可见",
            "同屏最多 3 个具名角色",
            "孩子能模仿的具体动作",
            "≤12 个词",
            "重复",
            "jump-scare",
            "血腥",
            "恋爱线",
            "讽刺",
            "本集内解决",
            "好奇心钩子",
            "肢体喜剧",
            "色彩明亮",
        ):
            assert fragment in block

    def test_never_asks_to_like_or_follow(self):
        block = render_audience_section("儿童 6-10 岁")
        assert "点赞" not in block
        assert "关注" not in block
