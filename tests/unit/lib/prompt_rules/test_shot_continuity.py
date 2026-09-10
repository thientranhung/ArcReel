"""``render_shot_continuity_rules`` 读取 profile 目录下的规则正文；内容断言钉住关键要素。"""

from pathlib import Path

import pytest

from lib.prompt_rules.shot_continuity import SHOT_CONTINUITY_RULES_FILE, render_shot_continuity_rules


def test_rules_come_from_the_profile_directory_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """规则正文住在 agent profile 里，换 profile 目录即换文本——不在导入时定死。"""
    references = tmp_path / ".claude" / "references"
    references.mkdir(parents=True)
    (references / SHOT_CONTINUITY_RULES_FILE).write_text("替身连续性规则", encoding="utf-8")
    monkeypatch.setenv("ARCREEL_PROFILE_DIR", str(tmp_path))

    assert render_shot_continuity_rules() == "替身连续性规则"


class TestShotContinuityRulesContent:
    """真实文案断言（见 docs/research/learn-from-waoowaoo-2026-09-10.md §1.3）。

    不 monkeypatch profile 目录，直接读仓库里真实的 ``shot-continuity-rules.md``——具体措辞
    是本次改动的交付物，钉住关键要素而非只测「文件可换」。
    """

    def test_covers_entry_exit_state_rule(self) -> None:
        text = render_shot_continuity_rules()
        assert "入口状态" in text
        assert "出口状态" in text
        assert "状态只能向前推进" in text

    def test_covers_reference_locks_identity_only(self) -> None:
        text = render_shot_continuity_rules()
        assert "参考图只锁定身份" in text
        assert "直视镜头" in text
        assert "一个目的" in text

    def test_covers_performance_discipline(self) -> None:
        text = render_shot_continuity_rules()
        assert "情绪形容词" in text
        assert "僵住 → 确认 → 释放" in text
        assert "最多一次情绪转折" in text

    def test_covers_camera_rules(self) -> None:
        text = render_shot_continuity_rules()
        assert "叙事职能" in text
        assert "直切" in text

    def test_covers_dialogue_and_sound_rules(self) -> None:
        text = render_shot_continuity_rules()
        assert "说话人必须在画面内" in text
        assert "不写背景音乐" in text

    def test_covers_fixed_negative_constraints(self) -> None:
        text = render_shot_continuity_rules()
        assert "STORYBOARD_AVOID_ITEMS" in text
        assert "VIDEO_AVOID_ITEMS" in text
