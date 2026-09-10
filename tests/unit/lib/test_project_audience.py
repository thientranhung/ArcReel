"""目标受众字段的读时解析：显式字段优先，退回 overview 文本兜底。"""

from __future__ import annotations

from lib.project_audience import PROJECT_AUDIENCE_FIELD, project_audience, resolve_project_audience_text


class TestProjectAudience:
    def test_reads_explicit_field(self) -> None:
        assert project_audience({PROJECT_AUDIENCE_FIELD: "儿童 6-10 岁"}) == "儿童 6-10 岁"

    def test_missing_field_is_none(self) -> None:
        assert project_audience({}) is None

    def test_blank_field_is_none(self) -> None:
        assert project_audience({PROJECT_AUDIENCE_FIELD: "   "}) is None

    def test_non_string_field_is_none(self) -> None:
        assert project_audience({PROJECT_AUDIENCE_FIELD: 123}) is None

    def test_non_mapping_project_is_none(self) -> None:
        assert project_audience(None) is None


class TestResolveProjectAudienceText:
    def test_explicit_field_takes_priority_over_overview(self) -> None:
        project = {
            PROJECT_AUDIENCE_FIELD: "儿童 6-10 岁",
            "overview": {"world_setting": "赛博朋克成人世界", "theme": "复仇"},
        }
        assert resolve_project_audience_text(project) == "儿童 6-10 岁"

    def test_falls_back_to_overview_world_setting_and_theme(self) -> None:
        project = {"overview": {"world_setting": "面向儿童的睡前故事世界", "theme": "友谊"}}
        text = resolve_project_audience_text(project)
        assert text is not None
        assert "面向儿童的睡前故事世界" in text
        assert "友谊" in text

    def test_no_explicit_field_and_empty_overview_is_none(self) -> None:
        assert resolve_project_audience_text({}) is None

    def test_overview_with_blank_fields_is_none(self) -> None:
        project = {"overview": {"world_setting": "", "theme": "   "}}
        assert resolve_project_audience_text(project) is None

    def test_non_mapping_project_is_none(self) -> None:
        assert resolve_project_audience_text(None) is None

    def test_non_mapping_overview_is_none(self) -> None:
        assert resolve_project_audience_text({"overview": "not a mapping"}) is None
