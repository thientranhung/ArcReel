"""视觉质检（Visual QA）：对已生成的资产图 / 分镜图 / 宫格合图做一次视觉复核。

本模块是纯逻辑层：构造评审请求、解析评审结果、按阈值判定 verdict、把结果投影成
``GenerationWarning``。它不做任何 IO——图片读取、文本 backend 解析、子进程调用都经
:class:`VisualQaBackend` 的具体实现（:class:`ProjectTextBackendVisualQa` /
:class:`ExternalCommandVisualQa`）注入，调用方（MCP 工具/服务层）负责装配。

verdict 由本模块按 ``min_pass_score`` 阈值重新计算（:func:`evaluate_verdict`），
不直接采信模型返回的 ``verdict`` 字段——模型的评分数值是唯一可信输入，判定逻辑
收在这一处，不同 backend 的评审提示词措辞差异不会导致判定口径漂移。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lib.generation_result import GenerationWarning
from lib.text_backends.base import ImageInput, TextGenerationRequest

#: 视觉质检发现问题时的 warning key（i18n：见 lib/i18n/{zh,en,vi}/errors.py）。
VISUAL_QA_REGENERATE_WARNING_KEY = "visual_qa.regenerate_suggested"

#: 项目级设置在 project.json 顶层的字段名。
VISUAL_QA_SETTINGS_FIELD = "visual_qa"

_SCORE_MIN = 1
_SCORE_MAX = 5


class VisualQaResult(BaseModel):
    """一次评审的评分与结论。

    ``content`` / ``asset`` / ``style`` / ``audience`` 是模型给出的四个维度评分
    （1-5，5 为最佳）；``verdict`` 是模型自己给出的初判，仅供参考——最终结论须经
    :func:`evaluate_verdict` 按调用方配置的 ``min_pass_score`` 重新计算。``notes``
    是可直接喂给 ``edit_images`` 的具体修改建议。
    """

    model_config = ConfigDict(extra="forbid")

    content: int = Field(ge=_SCORE_MIN, le=_SCORE_MAX, description="画面内容与期望（剧情/描述）的契合度")
    asset: int = Field(
        ge=_SCORE_MIN, le=_SCORE_MAX, description="资产身份一致性（与角色/场景/道具描述及参考图的贴合度）"
    )
    style: int = Field(ge=_SCORE_MIN, le=_SCORE_MAX, description="画风与项目风格的贴合度")
    audience: int = Field(ge=_SCORE_MIN, le=_SCORE_MAX, description="面向目标受众的适宜度")
    verdict: Literal["pass", "regenerate"]
    notes: str = Field(description="具体的修改建议，须可直接作为图片编辑指令使用")

    @property
    def scores(self) -> tuple[int, int, int, int]:
        return (self.content, self.asset, self.style, self.audience)


class _VisualQaResultList(BaseModel):
    """宫格评审的 wire 层包装：结构化输出的根须是对象，不能是裸数组。"""

    model_config = ConfigDict(extra="forbid")

    results: list[VisualQaResult]


def evaluate_verdict(scores: Sequence[int], min_pass_score: int) -> Literal["pass", "regenerate"]:
    """按阈值把评分序列判定为 verdict：最短板维度低于阈值即建议重新生成。

    阈值判定收在这一处，是唯一权威——模型自己给出的 ``verdict`` 字段不作数。
    """
    if not scores:
        raise ValueError("scores 不能为空")
    return "pass" if min(scores) >= min_pass_score else "regenerate"


def apply_min_pass_score(result: VisualQaResult, min_pass_score: int) -> VisualQaResult:
    """返回一份 ``verdict`` 按 ``min_pass_score`` 重新计算过的结果副本。"""
    verdict = evaluate_verdict(result.scores, min_pass_score)
    if verdict == result.verdict:
        return result
    return result.model_copy(update={"verdict": verdict})


class VisualQaCellExpectation(BaseModel):
    """宫格合图里一个格子的期望内容。"""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    scene_text: str = Field(default="", description="该格子对应分镜的画面描述（image_prompt 渲染文本）")


class VisualQaExpectation(BaseModel):
    """一次评审的期望依据：来自 ``lib.visual_artifact_provenance`` 对应 visual basis 的投影。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["asset", "storyboard", "grid"]
    asset_description: str = ""
    scene_text: str = ""
    style: str = ""
    style_description: str = ""
    audience: str = ""
    cells: list[VisualQaCellExpectation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> VisualQaExpectation:
        if self.kind == "grid" and not self.cells:
            raise ValueError("grid 期望必须提供至少一个 cell")
        if self.kind != "grid" and self.cells:
            raise ValueError(f"{self.kind} 期望不应携带 cells（仅 grid 使用）")
        if self.kind == "asset" and not self.asset_description.strip():
            raise ValueError("asset 期望必须提供 asset_description")
        if self.kind == "storyboard" and not self.scene_text.strip():
            raise ValueError("storyboard 期望必须提供 scene_text")
        return self


def _common_axes_instructions() -> str:
    return (
        "请从以下四个维度分别打 1-5 分（5 分最佳）：\n"
        "1. content：画面呈现的内容是否忠实于下面给出的期望描述；\n"
        "2. asset：画面中的资产（角色/场景/道具）身份是否与描述及参考图保持一致，"
        "没有明显的外观漂移；\n"
        "3. style：画面风格是否贴合项目设定的风格；\n"
        "4. audience：画面是否适合下面给出的目标受众（未给出受众时按通用尺度评估）。\n"
        "同时给出一个你自己的初步结论 verdict（pass 或 regenerate，仅供参考，"
        "最终是否需要重新生成由调用方按分数阈值判定），以及一段具体、可执行的修改建议 notes——"
        "notes 要写得像一条图片编辑指令（说清楚改哪里、怎么改），而不是笼统的评价。"
    )


def _build_single_prompt(expectation: VisualQaExpectation) -> str:
    lines = ["你正在对一张 AI 生成的图片做视觉质检。"]
    if expectation.kind == "asset":
        lines.append(f"这张图是一份资产设定图，期望描述：{expectation.asset_description}")
    else:
        lines.append(f"这张图是一个分镜画面，期望描述：{expectation.scene_text}")
    if expectation.style:
        lines.append(f"项目风格：{expectation.style}")
    if expectation.style_description:
        lines.append(f"风格细节：{expectation.style_description}")
    if expectation.audience:
        lines.append(f"目标受众：{expectation.audience}")
    lines.append(_common_axes_instructions())
    return "\n".join(lines)


def _build_grid_prompt(expectation: VisualQaExpectation) -> str:
    lines = [
        "你正在对一张 AI 生成的宫格合图做视觉质检。这张合图按顺序拼接了多个分镜画面，"
        "请逐格评审，按格子在下面列表中的顺序，为每一格分别输出一条评审结果，"
        "结果条数必须与格子数一致、顺序一一对应。"
    ]
    for index, cell in enumerate(expectation.cells):
        lines.append(f"第 {index + 1} 格（resource_id={cell.resource_id}）期望描述：{cell.scene_text}")
    if expectation.style:
        lines.append(f"项目风格：{expectation.style}")
    if expectation.style_description:
        lines.append(f"风格细节：{expectation.style_description}")
    if expectation.audience:
        lines.append(f"目标受众：{expectation.audience}")
    lines.append(_common_axes_instructions())
    return "\n".join(lines)


def build_visual_qa_request(image: ImageInput, expectation: VisualQaExpectation) -> TextGenerationRequest:
    """构造一次视觉质检的文本生成请求：单图走 :class:`VisualQaResult`，宫格走其列表包装。"""
    if expectation.kind == "grid":
        return TextGenerationRequest(
            prompt=_build_grid_prompt(expectation),
            response_schema=_VisualQaResultList,
            images=[image],
        )
    return TextGenerationRequest(
        prompt=_build_single_prompt(expectation),
        response_schema=VisualQaResult,
        images=[image],
    )


def _parse_visual_qa_output(text: str, response_schema: Any) -> VisualQaResult | list[VisualQaResult]:
    if response_schema is _VisualQaResultList:
        return _VisualQaResultList.model_validate_json(text).results
    return VisualQaResult.model_validate_json(text)


class VisualQaBackend(Protocol):
    """执行一次视觉质检评审的后端协议。"""

    async def review(self, request: TextGenerationRequest) -> VisualQaResult | list[VisualQaResult]: ...


@dataclass
class ProjectTextBackendVisualQa:
    """经项目配置解析出的文本 backend（``TextTaskType.VISUAL_QA``）驱动评审。

    解析口径与 ``STYLE_ANALYSIS`` 一致（见 ``server/routers/files.py`` 的
    ``upload_style_image``）：经 ``TextGenerator.create`` 按任务类型解析 backend 并自动记账。
    """

    project_name: str | None = None

    async def review(self, request: TextGenerationRequest) -> VisualQaResult | list[VisualQaResult]:
        # 延迟导入：避免 lib.visual_qa（纯逻辑模块）在模块加载期就拉入记账/DB 依赖链。
        from lib.providers import CallPurpose
        from lib.text_backends.base import TextTaskType
        from lib.text_generator import TextGenerator

        generator = await TextGenerator.create(TextTaskType.VISUAL_QA, self.project_name, purpose=CallPurpose.VISUAL_QA)
        result = await generator.generate(request, project_name=self.project_name)
        return _parse_visual_qa_output(result.text, request.response_schema)


class ExternalCommandVisualQaError(RuntimeError):
    """外部质检命令执行失败（非零退出码、超时、或输出不满足 schema）。"""


@dataclass
class ExternalCommandVisualQa:
    """经一条配置的外部命令模板执行评审（如把图片交给另一个本地 CLI agent 评审）。

    ``command_template`` 用 ``{image}`` / ``{output_schema}`` / ``{prompt}`` 三个占位符，
    例如 ``"codex exec -i {image} --output-schema {output_schema} {prompt}"``。三个值在替换前
    各自经 ``shlex.quote``，模板本身不必关心引号转义；子进程一律按参数列表调用（不经 shell），
    与 Windows 兼容规范一致。
    """

    command_template: str
    timeout_seconds: float = 120.0

    async def review(self, request: TextGenerationRequest) -> VisualQaResult | list[VisualQaResult]:
        if not request.images:
            raise ValueError("external visual QA command requires an image input")
        image = request.images[0]
        if image.path is None:
            raise ValueError("external visual QA command requires a local image path (ImageInput.path)")

        schema_dict = _resolve_response_schema_dict(request.response_schema)
        fd, schema_path = tempfile.mkstemp(prefix="visual_qa_schema_", suffix=".json", dir=tempfile.gettempdir())
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(schema_dict, f)

            command = self.command_template.format(
                image=shlex.quote(str(image.path)),
                output_schema=shlex.quote(schema_path),
                prompt=shlex.quote(request.prompt),
            )
            argv = shlex.split(command)
            if not argv:
                raise ValueError("visual_qa.external_command 不能为空")

            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise ExternalCommandVisualQaError(
                    f"外部视觉质检命令超时（{self.timeout_seconds}s）：{command}"
                ) from None
        finally:
            with contextlib.suppress(OSError):
                os.remove(schema_path)

        if proc.returncode != 0:
            raise ExternalCommandVisualQaError(
                f"外部视觉质检命令退出码 {proc.returncode}：{stderr.decode('utf-8', errors='replace')[:2000]}"
            )
        try:
            return _parse_visual_qa_output(stdout.decode("utf-8"), request.response_schema)
        except Exception as exc:
            raise ExternalCommandVisualQaError(f"外部视觉质检命令输出不满足 VisualQaResult schema：{exc}") from exc


def _resolve_response_schema_dict(response_schema: Any) -> dict:
    from lib.text_backends.base import resolve_schema

    if response_schema is _VisualQaResultList:
        return resolve_schema(_VisualQaResultList)
    return resolve_schema(VisualQaResult)


def visual_qa_warning(result: VisualQaResult) -> GenerationWarning | None:
    """把一份已按阈值判定过 verdict 的结果投影成 warning；``pass`` 时返回 ``None``。"""
    if result.verdict == "pass":
        return None
    return GenerationWarning(
        key=VISUAL_QA_REGENERATE_WARNING_KEY,
        params={
            "content": result.content,
            "asset": result.asset,
            "style": result.style,
            "audience": result.audience,
            "notes": result.notes,
        },
    )


class VisualQaSettings(BaseModel):
    """项目级视觉质检设置（``project.json`` 顶层 ``visual_qa`` 字段）。

    PR A 只落地存储与校验：``enabled`` 目前不驱动任何自动行为（自动钩子/自动重生成/UI
    是 PR B 的范围）。
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    auto_regenerate_max: int = Field(default=0, ge=0)
    min_pass_score: int = Field(default=3, ge=_SCORE_MIN, le=_SCORE_MAX)


def resolve_visual_qa_settings(project: Mapping[str, Any] | None) -> VisualQaSettings:
    """读取项目的视觉质检设置；缺失/形状不对一律回退默认值（未设=关闭，与写入侧无关）。"""
    if not isinstance(project, Mapping):
        return VisualQaSettings()
    raw = project.get(VISUAL_QA_SETTINGS_FIELD)
    if not isinstance(raw, Mapping):
        return VisualQaSettings()
    try:
        return VisualQaSettings.model_validate(raw)
    except Exception:
        return VisualQaSettings()


__all__ = [
    "VISUAL_QA_REGENERATE_WARNING_KEY",
    "VISUAL_QA_SETTINGS_FIELD",
    "ExternalCommandVisualQa",
    "ExternalCommandVisualQaError",
    "ProjectTextBackendVisualQa",
    "VisualQaBackend",
    "VisualQaCellExpectation",
    "VisualQaExpectation",
    "VisualQaResult",
    "VisualQaSettings",
    "apply_min_pass_score",
    "build_visual_qa_request",
    "evaluate_verdict",
    "resolve_visual_qa_settings",
    "visual_qa_warning",
]
