"""视觉质检（Visual QA）执行层：对一批 id 的当前图各跑一次评审。

只读评审：不入生成队列、不产版本、不写产物清单——它评审的是已经生成好的图，不生成新图。
「当前图」解析复用 ``image_edit_tasks.resolve_current_image_rel``（编辑链路的同一口径），
期望依据复用 ``lib.prompt_utils.project_storyboard_image_prompt`` 与 project.json 顶层
``style`` / ``style_description``、资产条目的 ``description`` 字段——都是渲染/编辑链路
已在用的同一批字段，不另造一套。

结果写一份 sidecar JSON（``<artifact>.png.qa.json``），与 Artifact Manifest（ADR 0062）
的严格契约保持分离——质检结果不是 manifest 承认的产物身份证据，只是旁路记录。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lib.asset_types import ASSET_SPECS, resolve_asset_key
from lib.grid_manager import GridManager
from lib.project_audience import project_audience
from lib.project_manager import ProjectManager, get_project_manager
from lib.prompt_utils import project_storyboard_image_prompt
from lib.storyboard_sequence import find_storyboard_item, get_storyboard_items
from lib.text_backends.base import ImageInput
from lib.visual_qa import (
    VisualQaBackend,
    VisualQaCellExpectation,
    VisualQaExpectation,
    VisualQaResult,
    apply_min_pass_score,
    build_visual_qa_request,
    resolve_visual_qa_settings,
    visual_qa_warning,
)
from server.services.image_edit_tasks import resolve_current_image_rel

VisualQaResourceType = Literal["character", "scene", "prop", "storyboard", "grid"]

#: run_visual_qa 支持的资源类型（不含 product / 角色衍生——PR A 范围之外，PR B 视需要再扩）。
VISUAL_QA_RESOURCE_TYPES: tuple[VisualQaResourceType, ...] = ("character", "scene", "prop", "storyboard", "grid")


class VisualQaResourceNotFound(LookupError):
    """请求的资源 id 在项目里不存在。"""


class VisualQaImageMissing(LookupError):
    """资源存在，但尚无已登记的当前图——没有产物可评审。"""


@dataclass(frozen=True, slots=True)
class VisualQaIdOutcome:
    result: VisualQaResult
    warning: dict[str, Any] | None
    sidecar_path: str


@dataclass(frozen=True, slots=True)
class VisualQaRunResult:
    outcomes: dict[str, VisualQaIdOutcome]

    @property
    def results(self) -> dict[str, VisualQaResult]:
        return {unit_id: outcome.result for unit_id, outcome in self.outcomes.items()}

    @property
    def warnings_added(self) -> dict[str, dict[str, Any]]:
        return {unit_id: outcome.warning for unit_id, outcome in self.outcomes.items() if outcome.warning is not None}


def _sidecar_path(artifact_path: Path) -> Path:
    """Sidecar 路径：``<artifact>.qa.json``，与产物同目录，不占用 manifest 命名空间。"""
    return artifact_path.with_name(artifact_path.name + ".qa.json")


def _write_sidecar(path: Path, result: VisualQaResult) -> None:
    path.write_text(json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")


def _project_style(project: Mapping[str, Any]) -> tuple[str, str]:
    style = project.get("style")
    style_description = project.get("style_description")
    return (
        style if isinstance(style, str) else "",
        style_description if isinstance(style_description, str) else "",
    )


def _require_asset_entry(project: Mapping[str, Any], resource_type: str, resource_id: str) -> Mapping[str, Any]:
    """校验资产 id 存在，返回其条目；存在性与「有没有当前图」是两回事，分开判定。"""
    spec = ASSET_SPECS[resource_type]
    bucket = project.get(spec.bucket_key)
    if not isinstance(bucket, Mapping):
        raise VisualQaResourceNotFound(f"{resource_type} {resource_id!r} 不存在")
    key = resolve_asset_key(bucket, resource_id)
    if key is None:
        raise VisualQaResourceNotFound(f"{resource_type} {resource_id!r} 不存在")
    entry = bucket[key]
    if not isinstance(entry, Mapping):
        raise VisualQaResourceNotFound(f"{resource_type} {resource_id!r} 不存在")
    return entry


def _asset_expectation(project: Mapping[str, Any], entry: Mapping[str, Any], audience: str) -> VisualQaExpectation:
    description = entry.get("description")
    style, style_description = _project_style(project)
    return VisualQaExpectation(
        kind="asset",
        asset_description=str(description or ""),
        style=style,
        style_description=style_description,
        audience=audience,
    )


def _storyboard_scene_text(image_prompt: object, style: str) -> str:
    try:
        prompt, _style_input = project_storyboard_image_prompt(image_prompt, style)
    except ValueError:
        return ""
    if isinstance(prompt, str):
        return prompt
    return json.dumps(prompt, ensure_ascii=False)


def _storyboard_expectation(
    project: Mapping[str, Any], script: Mapping[str, Any], resource_id: str, audience: str
) -> tuple[str, VisualQaExpectation]:
    items, id_field, *_ = get_storyboard_items(dict(script))
    resolved = find_storyboard_item(items, id_field, resource_id)
    if resolved is None:
        raise VisualQaResourceNotFound(f"storyboard {resource_id!r} 不存在")
    item = resolved[0]
    resolved_id = str(item.get(id_field) or resource_id)
    style, style_description = _project_style(project)
    scene_text = _storyboard_scene_text(item.get("image_prompt"), style)
    return resolved_id, VisualQaExpectation(
        kind="storyboard",
        scene_text=scene_text,
        style=style,
        style_description=style_description,
        audience=audience,
    )


def _grid_expectation(
    project: Mapping[str, Any], script: Mapping[str, Any], grid_id: str, project_path: Path, audience: str
) -> tuple[Path, VisualQaExpectation]:
    grid_manager = GridManager(project_path)
    grid = grid_manager.get(grid_id)
    if grid is None:
        raise VisualQaResourceNotFound(f"grid {grid_id!r} 不存在")
    if not grid.grid_image_path:
        raise VisualQaImageMissing(f"grid {grid_id!r} 尚无联合图产物")
    style, style_description = _project_style(project)
    items, id_field, *_ = get_storyboard_items(dict(script))
    item_by_id = {str(entry.get(id_field)): entry for entry in items if isinstance(entry, Mapping)}
    cells: list[VisualQaCellExpectation] = []
    for scene_id in grid.scene_ids:
        item = item_by_id.get(scene_id)
        scene_text = _storyboard_scene_text(item.get("image_prompt"), style) if item is not None else ""
        cells.append(VisualQaCellExpectation(resource_id=scene_id, scene_text=scene_text))
    expectation = VisualQaExpectation(
        kind="grid", cells=cells, style=style, style_description=style_description, audience=audience
    )
    return project_path / grid.grid_image_path, expectation


async def _resolve_one(
    *,
    project_name: str,
    project: Mapping[str, Any],
    project_path: Path,
    resource_type: VisualQaResourceType,
    resource_id: str,
    script: Mapping[str, Any] | None,
    audience: str,
) -> tuple[str, Path, VisualQaExpectation]:
    """解析单个 id 的（画面所属的 unit_id、当前图绝对路径、评审期望）。"""
    if resource_type == "grid":
        path, expectation = _grid_expectation(project, script or {}, resource_id, project_path, audience)
        return resource_id, path, expectation
    if resource_type == "storyboard":
        resolved_id, expectation = _storyboard_expectation(project, script or {}, resource_id, audience)
        rel = resolve_current_image_rel(dict(project), "storyboard", resolved_id, dict(script) if script else None)
        if not rel:
            raise VisualQaImageMissing(f"storyboard {resource_id!r} 尚无已登记的当前图")
        return resolved_id, project_path / rel, expectation
    entry = _require_asset_entry(project, resource_type, resource_id)
    rel = resolve_current_image_rel(dict(project), resource_type, resource_id, None)
    if not rel:
        raise VisualQaImageMissing(f"{resource_type} {resource_id!r} 尚无已登记的当前图")
    expectation = _asset_expectation(project, entry, audience)
    return resource_id, project_path / rel, expectation


async def run_visual_qa(
    project_name: str,
    resource_type: VisualQaResourceType,
    ids: list[str],
    *,
    backend: VisualQaBackend,
    script_file: str | None = None,
    projects: ProjectManager | None = None,
) -> VisualQaRunResult:
    """对 ``ids`` 逐个跑一次视觉质检评审，写 sidecar 并返回结果。

    ``script_file`` 在 ``resource_type`` 为 ``storyboard`` / ``grid`` 时必填——两者的期望依据
    要从对应集的剧本里读（分镜 image_prompt / 宫格 frame_chain），与 ``edit_images`` 工具
    对 storyboard 要求 ``script_file`` 同一约束。
    """
    if resource_type not in VISUAL_QA_RESOURCE_TYPES:
        raise ValueError(f"resource_type 必须是 {list(VISUAL_QA_RESOURCE_TYPES)} 之一，收到 {resource_type!r}")
    if not ids:
        raise ValueError("ids 不能为空")
    if resource_type in ("storyboard", "grid") and not script_file:
        raise ValueError(f"resource_type={resource_type} 时 script_file 必填")

    pm = projects if projects is not None else get_project_manager()

    def _load() -> tuple[dict[str, Any], Path, dict[str, Any] | None]:
        project = pm.load_project(project_name)
        project_path = pm.get_project_path(project_name)
        script = pm.load_script(project_name, script_file) if script_file else None
        return project, project_path, script

    project, project_path, script = await asyncio.to_thread(_load)
    settings = resolve_visual_qa_settings(project)
    audience = project_audience(project) or ""

    outcomes: dict[str, VisualQaIdOutcome] = {}
    for requested_id in ids:
        unit_id, image_path, expectation = await _resolve_one(
            project_name=project_name,
            project=project,
            project_path=project_path,
            resource_type=resource_type,
            resource_id=requested_id,
            script=script,
            audience=audience,
        )
        if not await asyncio.to_thread(image_path.exists):
            raise VisualQaImageMissing(f"{resource_type} {requested_id!r} 的当前图不存在于磁盘：{image_path}")

        request = build_visual_qa_request(ImageInput(path=image_path), expectation)
        raw_result = await backend.review(request)
        if isinstance(raw_result, list):
            if len(raw_result) != len(expectation.cells):
                raise ValueError(f"宫格评审返回 {len(raw_result)} 条结果，与格子数 {len(expectation.cells)} 不一致")
            for cell, cell_result in zip(expectation.cells, raw_result, strict=True):
                final = apply_min_pass_score(cell_result, settings.min_pass_score)
                sidecar = _sidecar_path(
                    image_path.with_name(f"{image_path.stem}__{cell.resource_id}{image_path.suffix}")
                )
                await asyncio.to_thread(_write_sidecar, sidecar, final)
                warning = visual_qa_warning(final)
                outcomes[cell.resource_id] = VisualQaIdOutcome(
                    result=final,
                    warning=warning.model_dump() if warning is not None else None,
                    sidecar_path=str(sidecar),
                )
            continue

        final = apply_min_pass_score(raw_result, settings.min_pass_score)
        sidecar = _sidecar_path(image_path)
        await asyncio.to_thread(_write_sidecar, sidecar, final)
        warning = visual_qa_warning(final)
        outcomes[unit_id] = VisualQaIdOutcome(
            result=final,
            warning=warning.model_dump() if warning is not None else None,
            sidecar_path=str(sidecar),
        )

    return VisualQaRunResult(outcomes=outcomes)


__all__ = [
    "VISUAL_QA_RESOURCE_TYPES",
    "VisualQaIdOutcome",
    "VisualQaImageMissing",
    "VisualQaResourceNotFound",
    "VisualQaRunResult",
    "run_visual_qa",
]
