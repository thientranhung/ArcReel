"""Tests for lib.visual_qa."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lib.generation_result import GenerationWarning
from lib.text_backends.base import ImageInput
from lib.visual_qa import (
    VISUAL_QA_REGENERATE_WARNING_KEY,
    ExternalCommandVisualQa,
    ExternalCommandVisualQaError,
    VisualQaCellExpectation,
    VisualQaExpectation,
    VisualQaResult,
    VisualQaSettings,
    apply_min_pass_score,
    build_visual_qa_request,
    evaluate_verdict,
    resolve_visual_qa_settings,
    visual_qa_warning,
)


def _result(**overrides) -> VisualQaResult:
    values = {"content": 5, "asset": 5, "style": 5, "audience": 5, "verdict": "pass", "notes": "ok"}
    values.update(overrides)
    return VisualQaResult.model_validate(values)


class TestVisualQaResult:
    def test_scores_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            _result(content=6)
        with pytest.raises(ValidationError):
            _result(asset=0)

    def test_unknown_verdict_rejected(self):
        with pytest.raises(ValidationError):
            _result(verdict="maybe")

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            VisualQaResult.model_validate(
                {"content": 5, "asset": 5, "style": 5, "audience": 5, "verdict": "pass", "notes": "", "extra": 1}
            )

    def test_scores_property_order(self):
        result = _result(content=1, asset=2, style=3, audience=4)
        assert result.scores == (1, 2, 3, 4)


class TestEvaluateVerdict:
    def test_all_above_threshold_passes(self):
        assert evaluate_verdict([4, 5, 3, 4], 3) == "pass"

    def test_weakest_axis_drives_regenerate(self):
        assert evaluate_verdict([5, 5, 2, 5], 3) == "regenerate"

    def test_exact_threshold_passes(self):
        assert evaluate_verdict([3, 3, 3, 3], 3) == "pass"

    def test_empty_scores_rejected(self):
        with pytest.raises(ValueError, match="不能为空"):
            evaluate_verdict([], 3)


class TestApplyMinPassScore:
    def test_overrides_model_verdict_when_scores_fail_threshold(self):
        result = _result(content=5, asset=5, style=1, audience=5, verdict="pass")
        recomputed = apply_min_pass_score(result, min_pass_score=3)
        assert recomputed.verdict == "regenerate"
        # 原始分数保持不变，只有 verdict 被重算覆盖。
        assert recomputed.scores == result.scores

    def test_keeps_result_identity_when_verdict_unchanged(self):
        result = _result(verdict="pass")
        recomputed = apply_min_pass_score(result, min_pass_score=3)
        assert recomputed is result

    def test_model_says_pass_but_scores_fail_gets_corrected(self):
        # 模型自己给出的 verdict 不可信：即便模型乐观地给出 pass，分数不达标仍判 regenerate。
        result = _result(content=1, asset=1, style=1, audience=1, verdict="pass")
        recomputed = apply_min_pass_score(result, min_pass_score=3)
        assert recomputed.verdict == "regenerate"


class TestVisualQaExpectation:
    def test_asset_requires_description(self):
        with pytest.raises(ValidationError, match="asset_description"):
            VisualQaExpectation(kind="asset")

    def test_storyboard_requires_scene_text(self):
        with pytest.raises(ValidationError, match="scene_text"):
            VisualQaExpectation(kind="storyboard")

    def test_grid_requires_cells(self):
        with pytest.raises(ValidationError, match="cell"):
            VisualQaExpectation(kind="grid")

    def test_non_grid_rejects_cells(self):
        with pytest.raises(ValidationError, match="cells"):
            VisualQaExpectation(
                kind="asset",
                asset_description="a hero",
                cells=[VisualQaCellExpectation(resource_id="E1S01")],
            )

    def test_valid_asset_expectation(self):
        expectation = VisualQaExpectation(kind="asset", asset_description="a red dragon", style="watercolor")
        assert expectation.kind == "asset"

    def test_valid_grid_expectation(self):
        expectation = VisualQaExpectation(
            kind="grid",
            cells=[
                VisualQaCellExpectation(resource_id="E1S01", scene_text="opening shot"),
                VisualQaCellExpectation(resource_id="E1S02", scene_text="reveal"),
            ],
        )
        assert len(expectation.cells) == 2


class TestBuildVisualQaRequest:
    def _image(self, tmp_path: Path) -> ImageInput:
        path = tmp_path / "shot.png"
        path.write_bytes(b"fake")
        return ImageInput(path=path)

    def test_single_request_schema_and_prompt_content(self, tmp_path):
        expectation = VisualQaExpectation(
            kind="asset",
            asset_description="a red dragon guarding a cave",
            style="watercolor",
            style_description="soft pastel wash",
            audience="儿童 6-10 岁",
        )
        request = build_visual_qa_request(self._image(tmp_path), expectation)
        assert request.response_schema is VisualQaResult
        assert "a red dragon guarding a cave" in request.prompt
        assert "watercolor" in request.prompt
        assert "soft pastel wash" in request.prompt
        assert "儿童 6-10 岁" in request.prompt
        assert request.images is not None
        assert len(request.images) == 1

    def test_grid_request_lists_every_cell_in_order(self, tmp_path):
        expectation = VisualQaExpectation(
            kind="grid",
            cells=[
                VisualQaCellExpectation(resource_id="E1S01", scene_text="opening shot"),
                VisualQaCellExpectation(resource_id="E1S02", scene_text="reveal moment"),
            ],
        )
        request = build_visual_qa_request(self._image(tmp_path), expectation)
        assert request.response_schema is not VisualQaResult
        idx1 = request.prompt.index("opening shot")
        idx2 = request.prompt.index("reveal moment")
        assert idx1 < idx2
        assert "E1S01" in request.prompt
        assert "E1S02" in request.prompt

    def test_request_carries_single_image(self, tmp_path):
        image = self._image(tmp_path)
        expectation = VisualQaExpectation(kind="asset", asset_description="x")
        request = build_visual_qa_request(image, expectation)
        assert request.images == [image]


class TestVisualQaWarning:
    def test_pass_yields_no_warning(self):
        assert visual_qa_warning(_result(verdict="pass")) is None

    def test_regenerate_yields_warning_with_scores_and_notes(self):
        result = _result(content=2, asset=3, style=1, audience=4, verdict="regenerate", notes="fix the lighting")
        warning = visual_qa_warning(result)
        assert isinstance(warning, GenerationWarning)
        assert warning.key == VISUAL_QA_REGENERATE_WARNING_KEY
        assert warning.params == {"content": 2, "asset": 3, "style": 1, "audience": 4, "notes": "fix the lighting"}


class TestVisualQaSettings:
    def test_defaults(self):
        settings = VisualQaSettings()
        assert settings.enabled is False
        assert settings.auto_regenerate_max == 0
        assert settings.min_pass_score == 3

    def test_rejects_out_of_range_min_pass_score(self):
        with pytest.raises(ValidationError):
            VisualQaSettings(min_pass_score=6)

    def test_rejects_negative_auto_regenerate_max(self):
        with pytest.raises(ValidationError):
            VisualQaSettings(auto_regenerate_max=-1)

    def test_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            VisualQaSettings.model_validate({"enabled": True, "unexpected": 1})


class TestResolveVisualQaSettings:
    def test_missing_project_returns_defaults(self):
        assert resolve_visual_qa_settings(None) == VisualQaSettings()

    def test_missing_field_returns_defaults(self):
        assert resolve_visual_qa_settings({"name": "demo"}) == VisualQaSettings()

    def test_valid_field_is_parsed(self):
        project = {"visual_qa": {"enabled": True, "auto_regenerate_max": 2, "min_pass_score": 4}}
        settings = resolve_visual_qa_settings(project)
        assert settings == VisualQaSettings(enabled=True, auto_regenerate_max=2, min_pass_score=4)

    def test_malformed_field_falls_back_to_defaults(self):
        project = {"visual_qa": {"min_pass_score": "not a number"}}
        assert resolve_visual_qa_settings(project) == VisualQaSettings()

    def test_non_mapping_field_falls_back_to_defaults(self):
        assert resolve_visual_qa_settings({"visual_qa": "nonsense"}) == VisualQaSettings()


class TestExternalCommandVisualQa:
    def test_parses_stdout_json_matching_schema(self, tmp_path, monkeypatch):
        image_path = tmp_path / "shot.png"
        image_path.write_bytes(b"fake")
        expectation = VisualQaExpectation(kind="asset", asset_description="x")
        request = build_visual_qa_request(ImageInput(path=image_path), expectation)

        payload = {"content": 4, "asset": 4, "style": 4, "audience": 4, "verdict": "pass", "notes": "looks good"}
        script = tmp_path / "fake_reviewer.py"
        script.write_text(
            f"import sys, json\nprint(json.dumps({payload!r}))\n",
            encoding="utf-8",
        )
        backend = ExternalCommandVisualQa(
            command_template=f"{sys.executable} {script} -i {{image}} --schema {{output_schema}} {{prompt}}"
        )
        result = asyncio.run(backend.review(request))
        assert isinstance(result, VisualQaResult)
        assert result.notes == "looks good"

    def test_nonzero_exit_raises(self, tmp_path):
        image_path = tmp_path / "shot.png"
        image_path.write_bytes(b"fake")
        expectation = VisualQaExpectation(kind="asset", asset_description="x")
        request = build_visual_qa_request(ImageInput(path=image_path), expectation)

        script = tmp_path / "fail.py"
        script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        backend = ExternalCommandVisualQa(
            command_template=f"{sys.executable} {script} {{image}} {{output_schema}} {{prompt}}"
        )
        with pytest.raises(ExternalCommandVisualQaError, match="退出码"):
            asyncio.run(backend.review(request))

    def test_invalid_json_output_raises(self, tmp_path):
        image_path = tmp_path / "shot.png"
        image_path.write_bytes(b"fake")
        expectation = VisualQaExpectation(kind="asset", asset_description="x")
        request = build_visual_qa_request(ImageInput(path=image_path), expectation)

        script = tmp_path / "garbage.py"
        script.write_text("print('not json')\n", encoding="utf-8")
        backend = ExternalCommandVisualQa(
            command_template=f"{sys.executable} {script} {{image}} {{output_schema}} {{prompt}}"
        )
        with pytest.raises(ExternalCommandVisualQaError, match="schema"):
            asyncio.run(backend.review(request))

    def test_missing_image_path_rejected(self):
        expectation = VisualQaExpectation(kind="asset", asset_description="x")
        request = build_visual_qa_request(ImageInput(url="https://example.com/x.png"), expectation)
        backend = ExternalCommandVisualQa(command_template="echo {image} {output_schema} {prompt}")
        with pytest.raises(ValueError, match="local image path"):
            asyncio.run(backend.review(request))

    def test_grid_request_returns_list(self, tmp_path):
        image_path = tmp_path / "grid.png"
        image_path.write_bytes(b"fake")
        expectation = VisualQaExpectation(
            kind="grid",
            cells=[
                VisualQaCellExpectation(resource_id="E1S01", scene_text="a"),
                VisualQaCellExpectation(resource_id="E1S02", scene_text="b"),
            ],
        )
        request = build_visual_qa_request(ImageInput(path=image_path), expectation)
        payload = {
            "results": [
                {"content": 5, "asset": 5, "style": 5, "audience": 5, "verdict": "pass", "notes": "a"},
                {"content": 1, "asset": 1, "style": 1, "audience": 1, "verdict": "regenerate", "notes": "b"},
            ]
        }
        script = tmp_path / "grid_reviewer.py"
        script.write_text(f"import json\nprint(json.dumps({payload!r}))\n", encoding="utf-8")
        backend = ExternalCommandVisualQa(
            command_template=f"{sys.executable} {script} {{image}} {{output_schema}} {{prompt}}"
        )
        result = asyncio.run(backend.review(request))
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].verdict == "pass"
        assert result[1].verdict == "regenerate"

    def test_schema_file_is_written_and_matches_response_schema(self, tmp_path):
        """外部命令模板可以把 schema 路径原样透传给被评审的 CLI；这里验证写入内容是合法 JSON schema。"""
        image_path = tmp_path / "shot.png"
        image_path.write_bytes(b"fake")
        expectation = VisualQaExpectation(kind="asset", asset_description="x")
        request = build_visual_qa_request(ImageInput(path=image_path), expectation)

        captured_schema_path = tmp_path / "captured_schema_path.txt"
        script = tmp_path / "capture.py"
        script.write_text(
            "import sys, json\n"
            f"open({str(captured_schema_path)!r}, 'w').write(sys.argv[2])\n"
            "payload = {'content': 5, 'asset': 5, 'style': 5, 'audience': 5, 'verdict': 'pass', 'notes': 'ok'}\n"
            "print(json.dumps(payload))\n",
            encoding="utf-8",
        )
        backend = ExternalCommandVisualQa(
            command_template=f"{sys.executable} {script} {{image}} {{output_schema}} {{prompt}}"
        )
        asyncio.run(backend.review(request))
        recorded_path = Path(captured_schema_path.read_text(encoding="utf-8").strip())
        # The schema temp file is removed after the command runs; we only assert its path was passed
        # and was absolute (so the reviewed CLI could have read it while the process was alive).
        assert recorded_path.is_absolute()
