"""Side-effect-free projection of authoritative workflow facts into an executable plan."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lib.asset_types import ASSET_SPECS
from lib.config.cost_thresholds import cost_thresholds_usd
from lib.cost_estimate import UnitCostInput, aggregate_cost_estimate
from lib.generation_result import GenerationAction, GenerationProblem, ProviderCheckpoint
from lib.narration_delivery import POST_PRODUCTION, USE_TTS, NarrationDelivery
from lib.workflow_rules import WorkflowStepRule, workflow_rule
from lib.workflow_state import (
    WorkflowActionType,
    WorkflowBlocker,
    WorkflowCostEstimate,
    WorkflowNextAction,
    WorkflowStatus,
)

PositiveStrictInt = Annotated[int, Field(strict=True, gt=0)]


class WorkflowStepState(StrEnum):
    """Progress of the orchestration step, independent from artifact and task state."""

    COMPLETED = "completed"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PENDING = "pending"
    SKIPPED = "skipped"


class WorkflowPlanRequest(BaseModel):
    """Transient choices used to plan one request without changing project workflow state."""

    model_config = ConfigDict(extra="forbid")

    episode: int | None = Field(default=None, ge=1, strict=True)
    narration_delivery: NarrationDelivery | None = None
    confirmed_request_durations: dict[str, PositiveStrictInt] = Field(default_factory=dict)
    confirmed_cost: bool = False
    """Mirrors ``confirmed_request_durations``: explicit consent to a quote that
    crosses the project's (or global default) hard cost threshold — see
    ``lib.batch_admission.COST_CONFIRMATION_CODE``."""

    @field_validator("confirmed_request_durations")
    @classmethod
    def _valid_confirmed_durations(cls, value: dict[str, int]) -> dict[str, int]:
        for unit_id in value:
            if not unit_id.strip():
                raise ValueError("confirmed_request_durations keys must be non-empty unit ids")
        return value


class WorkflowNarrationDelivery(BaseModel):
    """The non-persistent delivery choice attached to this plan only."""

    model_config = ConfigDict(extra="forbid")

    selected: NarrationDelivery | None
    options: tuple[Literal["post_production"], Literal["use_tts"]] = (POST_PRODUCTION, USE_TTS)
    persisted: Literal[False] = False


class WorkflowTaskObservation(BaseModel):
    """One task axis, kept separate from provider submission and artifact currency."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    task_id: str
    batch_id: str | None = None
    task_type: str
    status: str
    provider_checkpoint: ProviderCheckpoint | None = None
    problem: GenerationProblem | None = None


class WorkflowStepContracts(BaseModel):
    """Existing deep-module contracts an action must cross when it executes."""

    model_config = ConfigDict(extra="forbid")

    script_edit: Literal["script_batch_edit/v1"] | None = None
    batch_admission: Literal["video_batch_admission/v1"] | None = None


class WorkflowPlanStep(BaseModel):
    """One ordered step without collapsing its artifact, task, and execution axes."""

    model_config = ConfigDict(extra="forbid")

    id: str
    state: WorkflowStepState
    required: bool
    action: WorkflowNextAction | None = None
    requested_ids: list[str] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    problems: list[GenerationProblem] = Field(default_factory=list)
    tasks: list[WorkflowTaskObservation] = Field(default_factory=list)
    admission: dict[str, Any] | None = None
    contracts: WorkflowStepContracts = Field(default_factory=WorkflowStepContracts)


class WorkflowPlan(BaseModel):
    """Versioned plan shared unchanged by REST and MCP adapters."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: WorkflowStatus
    narration_delivery: WorkflowNarrationDelivery
    steps: list[WorkflowPlanStep]
    blockers: list[WorkflowBlocker]
    problems: list[GenerationProblem]
    next_action: WorkflowNextAction


_ARTIFACT_BY_STEP: dict[str, str] = {
    "asset_inventory": "asset_inventory",
    "asset_sheets": "asset_sheets",
    "script_plan_content": "script_plan",
    "script_plan_review": "script_plan",
    "final_script": "script",
    "storyboard": "storyboards",
    "narration_delivery": "audio",
    "video": "videos",
}

_TASK_STEP: dict[str, str] = {
    "text_episode_plan": "episode_plan",
    "text_drama_script_plan": "script_plan_content",
    "text_narration_script_plan": "script_plan_content",
    "text_reference_script_plan": "script_plan_content",
    "text_episode_script": "final_script",
    **dict.fromkeys(ASSET_SPECS, "asset_sheets"),
    "storyboard": "storyboard",
    "grid": "storyboard",
    "tts": "narration_delivery",
    "video": "video",
    "reference_video": "video",
}


def _baseline_step_state(
    rule: WorkflowStepRule,
    *,
    index: int,
    current_index: int,
    status: WorkflowStatus,
) -> WorkflowStepState:
    if not rule.applicable:
        return WorkflowStepState.SKIPPED
    if index < current_index:
        return WorkflowStepState.COMPLETED
    if index > current_index:
        return WorkflowStepState.PENDING
    if status.blockers or status.next_action.type is WorkflowActionType.NONE:
        return WorkflowStepState.BLOCKED
    return WorkflowStepState.READY


def _current_rule_index(status: WorkflowStatus, rules: tuple[WorkflowStepRule, ...]) -> int:
    if status.next_action.type is WorkflowActionType.REPAIR_VIDEO_UNITS:
        return next(index for index, rule in enumerate(rules) if rule.id == "script_structure")
    for index, rule in enumerate(rules):
        if rule.applicable and rule.checkpoint == status.state:
            return index
    raise ValueError(f"workflow state {status.state!r} is absent from its mode rule")


def _admission_problems(admission: dict[str, Any] | None) -> list[GenerationProblem]:
    if not admission:
        return []
    problems: list[GenerationProblem] = []
    for unit in admission.get("units", []):
        if not isinstance(unit, dict):
            continue
        raw_problems = unit.get("problems", [])
        if not isinstance(raw_problems, list):
            continue
        problems.extend(GenerationProblem.model_validate(raw) for raw in raw_problems)
    return problems


def _problem_unit_ids(problems: list[GenerationProblem]) -> list[str]:
    ids: list[str] = []
    for problem in problems:
        unit_id = problem.params.get("unit_id")
        if not isinstance(unit_id, str):
            admission = problem.params.get("speech_admission")
            unit_id = admission.get("unit_id") if isinstance(admission, dict) else None
        if isinstance(unit_id, str) and unit_id and unit_id not in ids:
            ids.append(unit_id)
    return ids


def _structure_action(
    problems: list[GenerationProblem],
    *,
    script_revision: str | None,
) -> WorkflowNextAction:
    return WorkflowNextAction(
        type=WorkflowActionType.PATCH_EPISODE_SCRIPT,
        args={
            "base_revision": script_revision,
            "problems": [problem.model_dump(mode="json") for problem in problems],
        },
        requested_ids=_problem_unit_ids(problems),
        reason=problems[0].detail,
    )


_COST_ESTIMATE_ACTIONS = frozenset(
    {
        WorkflowActionType.GENERATE_VIDEOS,
        WorkflowActionType.GENERATE_STORYBOARDS,
        WorkflowActionType.GENERATE_GRID,
        WorkflowActionType.GENERATE_ASSET_SHEETS,
        WorkflowActionType.GENERATE_TTS,
        WorkflowActionType.REGENERATE_TTS,
    }
)


def _unit_costs_from_admission(admission: dict[str, Any] | None) -> dict[str, UnitCostInput]:
    """Read the already-quoted per-unit cost off the batch admission's tickets.

    ``generate_videos`` needs no separate resolution pass: ``video_batch_admission``
    already quotes every unit's ``request_cost`` for the duration-confirmation UI, and
    this is the exact same figure a submission would be charged.
    """

    if not admission:
        return {}
    units: dict[str, UnitCostInput] = {}
    for unit in admission.get("units", []):
        if not isinstance(unit, dict):
            continue
        unit_id = unit.get("unit_id")
        if isinstance(unit_id, str) and unit_id:
            units[unit_id] = unit.get("request_cost")
    return units


def _with_cost_estimate(
    next_action: WorkflowNextAction,
    *,
    admission: dict[str, Any] | None,
    unit_cost_estimates: dict[str, UnitCostInput] | None,
    confirmed_cost: bool,
    soft_threshold_usd: float,
    hard_threshold_usd: float,
) -> WorkflowNextAction:
    """Attach ``cost_estimate`` to a generation ``next_action`` and gate on its threshold.

    A ``"confirm"`` threshold sets ``requires_confirmation`` unless the caller already
    consented (``confirmed_cost``) — mirroring ``confirmed_request_durations``. For
    ``generate_videos`` this ORs with whatever ``_admission_action`` already decided
    (its own confirmation may come from a duration tier, a cost tier, or both, already
    folded by ``lib.batch_admission.BatchAdmission.decision``).
    """

    if next_action.type not in _COST_ESTIMATE_ACTIONS or not next_action.requested_ids:
        return next_action
    source = (
        _unit_costs_from_admission(admission)
        if next_action.type is WorkflowActionType.GENERATE_VIDEOS
        else (unit_cost_estimates or {})
    )
    if not source:
        return next_action
    units = {unit_id: source.get(unit_id) for unit_id in next_action.requested_ids}
    payload = aggregate_cost_estimate(
        units, soft_threshold_usd=soft_threshold_usd, hard_threshold_usd=hard_threshold_usd
    )
    cost_estimate = WorkflowCostEstimate.model_validate(payload)
    requires_confirmation = next_action.requires_confirmation or (
        cost_estimate.threshold == "confirm" and not confirmed_cost
    )
    return next_action.model_copy(
        update={"cost_estimate": cost_estimate, "requires_confirmation": requires_confirmation}
    )


def _admission_action(
    admission: dict[str, Any],
    problems: list[GenerationProblem],
    requested_ids: list[str],
) -> WorkflowNextAction:
    requires_confirmation = admission.get("decision") == "confirmation_required"
    action = problems[0].action if problems else GenerationAction.CONFIRM_REQUEST_DURATION
    return WorkflowNextAction(
        type=WorkflowActionType(action.value),
        args={"admission": admission},
        requested_ids=requested_ids,
        requires_confirmation=requires_confirmation,
        reason=problems[0].detail if problems else "video batch requires confirmation",
    )


def build_workflow_plan(
    status: WorkflowStatus,
    *,
    narration_delivery: NarrationDelivery | None = None,
    structure_problems: list[GenerationProblem] | None = None,
    script_revision: str | None = None,
    task_observations: list[WorkflowTaskObservation] | None = None,
    admission: dict[str, Any] | None = None,
    unit_cost_estimates: dict[str, UnitCostInput] | None = None,
    confirmed_cost: bool = False,
    cost_thresholds_usd_override: tuple[float, float] | None = None,
) -> WorkflowPlan:
    """Project one immutable status snapshot and transient request observations.

    ``unit_cost_estimates`` carries per-``requested_ids`` cost for generation
    actions this module cannot price itself without I/O (image / audio): the
    async adapter (``server.services.workflow_planner``) resolves the current
    provider/model and any custom price, then hands in already-serialized
    amounts. ``generate_videos`` needs no such input — its cost is read
    straight off ``admission`` (already quoted by ``video_batch_admission``).
    """

    rule = workflow_rule(status.project.content_mode, status.project.generation_mode)
    rules = rule.steps
    current_index = _current_rule_index(status, rules)
    structure_problems = list(structure_problems or [])
    task_observations = list(task_observations or [])
    admission_problems = _admission_problems(admission)
    steps: list[WorkflowPlanStep] = []

    for index, step_rule in enumerate(rules):
        artifact_key = _ARTIFACT_BY_STEP.get(step_rule.id)
        step = WorkflowPlanStep(
            id=step_rule.id,
            state=_baseline_step_state(step_rule, index=index, current_index=current_index, status=status),
            required=step_rule.applicable,
            action=status.next_action if step_rule.checkpoint == status.state else None,
            requested_ids=(list(status.next_action.requested_ids) if step_rule.checkpoint == status.state else []),
            artifacts=dict(status.artifacts.get(artifact_key, {})) if artifact_key is not None else {},
            contracts=(
                WorkflowStepContracts(script_edit="script_batch_edit/v1")
                if step_rule.id == "script_structure"
                else WorkflowStepContracts(batch_admission="video_batch_admission/v1")
                if step_rule.id == "video"
                else WorkflowStepContracts()
            ),
        )
        if step_rule.id == "narration_delivery":
            step.required = status.state == "VIDEO" and status.next_action.type is WorkflowActionType.GENERATE_VIDEOS
        if step.artifacts.get("state") == "blocked" and step.state is not WorkflowStepState.SKIPPED:
            step.state = WorkflowStepState.BLOCKED
        steps.append(step)

    by_id = {step.id: step for step in steps}
    structure_step = by_id["script_structure"]
    if structure_problems:
        structure_step.state = WorkflowStepState.BLOCKED
        structure_step.problems = structure_problems
        structure_step.requested_ids = _problem_unit_ids(structure_problems)
        structure_step.action = _structure_action(structure_problems, script_revision=script_revision)
        for media_step in ("storyboard", "narration_delivery", "video"):
            if by_id[media_step].state is not WorkflowStepState.SKIPPED:
                by_id[media_step].state = WorkflowStepState.PENDING
                by_id[media_step].action = None

    delivery_step = by_id["narration_delivery"]
    delivery_index = next(index for index, item in enumerate(rules) if item.id == "narration_delivery")
    if not structure_problems and current_index >= delivery_index:
        # 音轨产物 blocked 只对本次选择 TTS 的请求成立：后期配音路径不消费 TTS 产物，
        # 交付选择尚未作出时两条路径都还开放，两种情况都不该被音轨阻断吞掉。
        tts_blocked = narration_delivery == USE_TTS and delivery_step.state is WorkflowStepState.BLOCKED
        if not tts_blocked:
            delivery_step.state = (
                WorkflowStepState.COMPLETED if narration_delivery is not None else WorkflowStepState.READY
            )

    for observation in task_observations:
        step_id = _TASK_STEP.get(observation.task_type)
        if step_id is None:
            continue
        step = by_id[step_id]
        step.tasks.append(observation)
        if observation.status in {"queued", "running", "cancelling"}:
            step.state = WorkflowStepState.ACTIVE

    video_step = by_id["video"]
    video_step.admission = admission
    video_step.problems = admission_problems
    if admission is not None and admission.get("decision") != "admitted" and not video_step.tasks:
        video_step.state = WorkflowStepState.BLOCKED

    active_tasks = [task for task in task_observations if task.status in {"queued", "running", "cancelling"}]
    if status.blockers:
        next_action = status.next_action
    elif structure_problems:
        next_action = _structure_action(structure_problems, script_revision=script_revision)
    elif active_tasks:
        # ponytail: fixed five-minute remote observation window; replace with per-task ETA only if providers expose it.
        batch_ids = list(dict.fromkeys(task.batch_id for task in active_tasks if task.batch_id is not None))
        next_action = WorkflowNextAction(
            type=WorkflowActionType.WAIT_FOR_TASK,
            args={
                "task_ids": [task.task_id for task in active_tasks],
                **({"batch_ids": batch_ids} if batch_ids else {}),
                "poll_after_seconds": 10,
                "max_poll_attempts": 30,
            },
            requested_ids=[task.unit_id for task in active_tasks],
            reason="workflow has active generation tasks",
        )
        for step in steps:
            if step.state is WorkflowStepState.ACTIVE:
                step.action = next_action
        if video_step.state is not WorkflowStepState.ACTIVE:
            video_step.action = None
    elif (
        status.state == "VIDEO"
        and status.next_action.type is WorkflowActionType.GENERATE_VIDEOS
        and narration_delivery is None
    ):
        next_action = WorkflowNextAction(
            type=WorkflowActionType.CHOOSE_NARRATION_DELIVERY,
            args={"options": [POST_PRODUCTION, USE_TTS]},
            requested_ids=list(status.next_action.requested_ids),
            reason="choose narration delivery for this video request",
        )
        delivery_step.action = next_action
        video_step.state = WorkflowStepState.PENDING
        video_step.action = None
    elif admission is not None and admission.get("decision") != "admitted":
        next_action = _admission_action(admission, admission_problems, list(status.next_action.requested_ids))
        video_step.action = next_action
    else:
        next_action = status.next_action

    original_next_action = next_action
    soft_threshold_usd, hard_threshold_usd = cost_thresholds_usd_override or cost_thresholds_usd(None)
    next_action = _with_cost_estimate(
        next_action,
        admission=admission,
        unit_cost_estimates=unit_cost_estimates,
        confirmed_cost=confirmed_cost,
        soft_threshold_usd=soft_threshold_usd,
        hard_threshold_usd=hard_threshold_usd,
    )
    if next_action is not original_next_action:
        for step in steps:
            if step.action is original_next_action:
                step.action = next_action

    return WorkflowPlan(
        status=status,
        narration_delivery=WorkflowNarrationDelivery(selected=narration_delivery),
        steps=steps,
        blockers=list(status.blockers),
        problems=[*structure_problems, *admission_problems],
        next_action=next_action,
    )


__all__ = [
    "WorkflowNarrationDelivery",
    "WorkflowPlan",
    "WorkflowPlanRequest",
    "WorkflowPlanStep",
    "WorkflowStepContracts",
    "WorkflowStepState",
    "WorkflowTaskObservation",
    "build_workflow_plan",
]
