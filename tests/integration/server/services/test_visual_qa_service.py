"""Integration tests for server.services.visual_qa_service.run_visual_qa."""

from __future__ import annotations

import json

import pytest

from lib.text_backends.base import TextGenerationRequest
from lib.visual_qa import VisualQaResult
from server.media_tools.context import ToolContext
from server.services.visual_qa_service import (
    VisualQaImageMissing,
    VisualQaResourceNotFound,
    run_visual_qa,
)


class FakeVisualQaBackend:
    """A scripted VisualQaBackend double: returns one queued result/list per call, in order."""

    def __init__(self, responses: list[VisualQaResult | list[VisualQaResult]]):
        self._responses = list(responses)
        self.requests: list[TextGenerationRequest] = []

    async def review(self, request: TextGenerationRequest) -> VisualQaResult | list[VisualQaResult]:
        self.requests.append(request)
        return self._responses.pop(0)


def _pass_result(**overrides) -> VisualQaResult:
    values = {"content": 5, "asset": 5, "style": 5, "audience": 5, "verdict": "pass", "notes": "looks great"}
    values.update(overrides)
    return VisualQaResult.model_validate(values)


def _regen_result(**overrides) -> VisualQaResult:
    values = {"content": 1, "asset": 1, "style": 1, "audience": 1, "verdict": "regenerate", "notes": "fix lighting"}
    values.update(overrides)
    return VisualQaResult.model_validate(values)


async def test_asset_review_writes_sidecar_and_returns_pass(idle_fake_ctx: ToolContext):
    project_path = idle_fake_ctx.project_path
    (project_path / "characters").mkdir()
    (project_path / "characters" / "zhangsan.png").write_bytes(b"png")
    idle_fake_ctx.pm.project_payload["characters"]["张三"]["character_sheet"] = "characters/zhangsan.png"

    backend = FakeVisualQaBackend([_pass_result()])
    outcome = await run_visual_qa("demo", "character", ["张三"], backend=backend, projects=idle_fake_ctx.pm)

    assert set(outcome.results) == {"张三"}
    assert outcome.results["张三"].verdict == "pass"
    assert outcome.warnings_added == {}

    sidecar = project_path / "characters" / "zhangsan.png.qa.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
    assert len(backend.requests) == 1
    images = backend.requests[0].images
    assert images is not None
    assert images[0].path == project_path / "characters" / "zhangsan.png"


async def test_asset_review_below_threshold_adds_warning(idle_fake_ctx: ToolContext):
    project_path = idle_fake_ctx.project_path
    (project_path / "characters").mkdir()
    (project_path / "characters" / "zhangsan.png").write_bytes(b"png")
    idle_fake_ctx.pm.project_payload["characters"]["张三"]["character_sheet"] = "characters/zhangsan.png"
    idle_fake_ctx.pm.project_payload["visual_qa"] = {"min_pass_score": 3}

    # 模型自己说 pass，但分数不达标——服务层须按阈值重新判定为 regenerate。
    backend = FakeVisualQaBackend([_regen_result(verdict="pass")])
    outcome = await run_visual_qa("demo", "character", ["张三"], backend=backend, projects=idle_fake_ctx.pm)

    assert outcome.results["张三"].verdict == "regenerate"
    assert "张三" in outcome.warnings_added
    warning = outcome.warnings_added["张三"]
    assert warning["key"] == "visual_qa.regenerate_suggested"
    assert warning["params"]["notes"] == "fix lighting"


async def test_storyboard_review_uses_registered_current_image(idle_fake_ctx: ToolContext):
    backend = FakeVisualQaBackend([_pass_result()])
    outcome = await run_visual_qa(
        "demo",
        "storyboard",
        ["E1S01"],
        backend=backend,
        script_file="episode_1.json",
        projects=idle_fake_ctx.pm,
    )

    assert set(outcome.results) == {"E1S01"}
    sidecar = idle_fake_ctx.project_path / "storyboards" / "scene_E1S01.png.qa.json"
    assert sidecar.exists()
    assert "村口黄昏" in backend.requests[0].prompt


async def test_storyboard_without_script_file_rejected(idle_fake_ctx: ToolContext):
    with pytest.raises(ValueError, match="script_file"):
        await run_visual_qa("demo", "storyboard", ["E1S01"], backend=FakeVisualQaBackend([]), projects=idle_fake_ctx.pm)


async def test_unknown_asset_id_raises_resource_not_found(idle_fake_ctx: ToolContext):
    with pytest.raises(VisualQaResourceNotFound):
        await run_visual_qa(
            "demo", "character", ["不存在的人"], backend=FakeVisualQaBackend([]), projects=idle_fake_ctx.pm
        )


async def test_asset_without_current_image_raises_image_missing(idle_fake_ctx: ToolContext):
    with pytest.raises(VisualQaImageMissing):
        await run_visual_qa("demo", "character", ["李四"], backend=FakeVisualQaBackend([]), projects=idle_fake_ctx.pm)
