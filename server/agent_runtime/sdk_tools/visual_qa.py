"""SDK MCP adapter for visual QA."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from server.media_tools.context import ToolContext, tool_outcome_response, tool_services
from server.tool_runtime import (
    RunVisualQaRequest,
    ToolOutcome,
    ToolProblem,
    ToolRequest,
    run_visual_qa,
)


def run_visual_qa_tool(ctx: ToolContext):
    @tool(
        "run_visual_qa",
        "对一批资源（character/scene/prop/storyboard/grid）的当前图各跑一次视觉质检评审，"
        "写一份评审结果 sidecar 并返回评分与建议。只读：不生成新图、不入生成队列、不改产物清单，"
        "结果里 verdict=regenerate 的条目，notes 可以直接作为 edit_images 的编辑指令。",
        {
            "type": "object",
            "properties": {
                "resource_type": {
                    "type": "string",
                    "enum": ["character", "scene", "prop", "storyboard", "grid"],
                    "description": "被评审资源的类型",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "待评审的资源 id 列表",
                },
                "script": {
                    "type": "string",
                    "description": "剧本文件名（纯文件名）；resource_type 为 storyboard/grid 时必填",
                },
            },
            "required": ["resource_type", "ids"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            request = RunVisualQaRequest.model_validate(args)
        except ValueError as exc:
            outcome = ToolOutcome(problem=ToolProblem("invalid_request", str(exc)))
        else:
            outcome = await run_visual_qa(ToolRequest(request), ctx.scope, ctx.caller, tool_services(ctx))
        return tool_outcome_response("visual_qa", outcome)

    return _handler


__all__ = ["run_visual_qa_tool"]
