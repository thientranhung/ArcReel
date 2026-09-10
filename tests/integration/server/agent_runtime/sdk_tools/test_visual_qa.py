"""Tests for the run_visual_qa SDK MCP tool adapter."""

from __future__ import annotations

import json

from server.agent_runtime.sdk_tools.visual_qa import run_visual_qa_tool
from server.media_tools.context import ToolContext
from tests.integration.server.agent_runtime.sdk_tools.sdk_tools_support import call


def test_run_visual_qa_registered() -> None:
    """run_visual_qa 须同时进 MCP 工具 id 集（前端 chip 三语校验依赖它）。"""
    from server.agent_runtime.sdk_tools import ARCREEL_MCP_TOOL_IDS

    assert "run_visual_qa" in ARCREEL_MCP_TOOL_IDS


async def test_run_visual_qa_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from lib.text_backends.base import TextGenerationResult
    from lib.text_generator import TextGenerator

    project_path = fake_ctx.project_path
    (project_path / "characters").mkdir(exist_ok=True)
    (project_path / "characters" / "zhangsan.png").write_bytes(b"png")
    fake_ctx.pm.project_payload["characters"]["张三"]["character_sheet"] = "characters/zhangsan.png"

    class _FakeGenerator:
        async def generate(self, request, project_name=None):
            del request, project_name
            payload = {"content": 5, "asset": 5, "style": 5, "audience": 5, "verdict": "pass", "notes": "ok"}
            return TextGenerationResult(text=json.dumps(payload), provider="fake", model="fake")

    async def fake_create(cls, task_type, project_name=None, *, purpose, user_id=None):
        del cls, task_type, project_name, purpose, user_id
        return _FakeGenerator()

    # 真正协作的边界在 lib.text_generator.TextGenerator（DB/供应商解析），不是被测的
    # lib.visual_qa.ProjectTextBackendVisualQa.review 本体——后者仍按真实逻辑执行。
    monkeypatch.setattr(TextGenerator, "create", classmethod(fake_create))

    tool_obj = run_visual_qa_tool(fake_ctx)
    out = await call(tool_obj, {"resource_type": "character", "ids": ["张三"]})

    assert out.get("is_error") is not True, out
    text = out["content"][0]["text"]
    assert "张三" in text


async def test_run_visual_qa_missing_image_reports_typed_problem(fake_ctx: ToolContext) -> None:
    tool_obj = run_visual_qa_tool(fake_ctx)
    out = await call(tool_obj, {"resource_type": "character", "ids": ["李四"]})

    assert out.get("is_error") is True
    text = out["content"][0]["text"]
    assert "image_missing" in text or "尚无" in text


async def test_run_visual_qa_storyboard_requires_script(fake_ctx: ToolContext) -> None:
    tool_obj = run_visual_qa_tool(fake_ctx)
    out = await call(tool_obj, {"resource_type": "storyboard", "ids": ["E1S01"]})

    assert out.get("is_error") is True
