"""``render_pacing_section`` 按 content_mode 交回 ``.claude/references/`` 下对应的规则文件，测试不抄文案措辞。"""

from pathlib import Path

import pytest

from lib.prompt_rules.episode_pacing import PACING_RULE_FILES, render_pacing_section


@pytest.mark.parametrize("content_mode", sorted(PACING_RULE_FILES))
def test_rules_come_from_the_profile_directory_at_call_time(
    content_mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规则正文住在 agent profile 里，换 profile 目录即换文本——不在导入时定死。"""
    references = tmp_path / ".claude" / "references"
    references.mkdir(parents=True)
    (references / PACING_RULE_FILES[content_mode]).write_text("替身节奏规则", encoding="utf-8")
    monkeypatch.setenv("ARCREEL_PROFILE_DIR", str(tmp_path))

    assert render_pacing_section(content_mode) == "替身节奏规则"


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown content_mode"):
        render_pacing_section("unknown")


class TestDramaRhythmRules:
    """短剧「夺注意力」节奏规则的真实文案（见 ADR/docs/research 里对 waoowaoo 的调研 §1.4）。

    不 monkeypatch profile 目录，直接读仓库里真实的 ``episode-pacing-drama.md``——
    这条规则组的具体措辞是本次改动的交付物，值得钉住关键要素而非只测「文件可换」。
    """

    def test_covers_the_2_6_8to10_second_cadence(self) -> None:
        text = render_pacing_section("drama")
        assert "~2 秒" in text
        assert "~6 秒" in text
        assert "8-10 秒" in text
        assert "不是分镜或镜头本身的长度" in text

    def test_covers_front_dense_middle_sparse_end_dense_density(self) -> None:
        text = render_pacing_section("drama")
        assert "前密、中疏、后密" in text
        assert "均匀分布" in text

    def test_covers_short_dialogue_and_consecutive_limit(self) -> None:
        text = render_pacing_section("drama")
        assert "硬字幕" in text
        assert "不超过 2 个" in text

    def test_covers_chosen_opening_and_forbidden_openings(self) -> None:
        text = render_pacing_section("drama")
        assert "选出来" in text
        assert "介绍环境" in text
        assert "自我介绍" in text
        assert "走路赶路" in text
        assert "寒暄问候" in text
        assert "同等或更强的强度兑现" in text

    def test_covers_cover_the_name_test(self) -> None:
        text = render_pacing_section("drama")
        assert "遮名测试" in text

    def test_covers_dual_purpose_dialogue_and_functional_silence(self) -> None:
        text = render_pacing_section("drama")
        assert "表面话题 + 潜台词" in text
        assert "沉默也是一种有功能的行动" in text

    def test_covers_ending_gives_audience_something_to_do(self) -> None:
        text = render_pacing_section("drama")
        assert "可做的事" in text
        assert "关键洞见" in text
        assert "不索取点赞或关注" in text
