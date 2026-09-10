"""SDK MCP adapter for the authoritative workflow planner."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from lib.workflow_plan import WorkflowPlanRequest
from server.media_tools.context import ToolContext, tool_outcome_response, tool_services
from server.tool_runtime import ToolOutcome, ToolProblem, ToolRequest, get_workflow_plan


def get_workflow_plan_tool(ctx: ToolContext):
    @tool(
        "get_workflow_plan",
        "读取只读的完整工作流计划。返回有序步骤、阻断原因、活动任务、视频准入、费用预估与唯一下一动作。"
        "生成类下一动作（generate_videos / generate_storyboards / generate_grid / "
        "generate_asset_sheets / generate_tts / regenerate_tts）在 next_action.cost_estimate 上"
        "携带每个 unit 的预估费用、汇总 total（跨币种时为 null）、无法定价的 unit 列表"
        "unpriced_units，以及阈值判定 threshold（ok/warn/confirm）。threshold 为 confirm 时"
        "next_action.requires_confirmation 为 true，须带 confirmed_cost=true 重新请求生成工具"
        "才会被放行（与 confirmed_request_durations 的确认流程相同机制）。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "narration_delivery": {
                    "type": "string",
                    "enum": ["post_production", "use_tts"],
                    "description": "本次视频请求的旁白交付选择；不写入项目 workflow。",
                },
                "confirmed_request_durations": {
                    "type": "object",
                    "additionalProperties": {"type": "integer", "minimum": 1},
                },
                "confirmed_cost": {
                    "type": "boolean",
                    "description": (
                        "对 next_action.cost_estimate.threshold=confirm 的显式确认；"
                        "为 true 时本次预览与随后的生成请求不再因费用阈值要求确认。"
                    ),
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            request = WorkflowPlanRequest.model_validate(args)
        except ValueError as exc:
            outcome = ToolOutcome(problem=ToolProblem("invalid_request", str(exc)))
        else:
            outcome = await get_workflow_plan(ToolRequest(request), ctx.scope, ctx.caller, tool_services(ctx))
        return tool_outcome_response("workflow_plan", outcome)

    return _handler


__all__ = ["get_workflow_plan_tool"]
