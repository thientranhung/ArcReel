"""Canonical direct-input bases for structured content artifacts.

These builders intentionally accept the full project mapping but project only formal
content semantics. Execution configuration does not participate in the currency of an
existing structured artifact.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from lib.artifact_manifest import ArtifactBasis
from lib.episode_ledger import (
    episode_outline_context,
    previous_episode_exit_state,
    previous_episode_outline_context,
)
from lib.episode_paths import episode_script_relpath
from lib.episode_target_duration import project_episode_target_duration
from lib.project_audience import resolve_project_audience_text
from lib.speech_rate import project_speech_rate_override, speech_rate_units_per_second
from lib.text_metrics import reading_unit_noun
from lib.text_utils import normalize_newlines

_STRUCTURED_CONTENT_MODES = frozenset({"narration", "drama"})
_GENERATION_MODES = frozenset({"storyboard", "reference_video"})
_SOURCE_KINDS = frozenset({"novel", "screenplay"})
_DEFAULT_SOURCE_LANGUAGE = "中文"
_AD_OVERVIEW_FIELDS = ("synopsis", "genre", "theme")

ScriptPlanPromptVariant = Literal["drama", "narration", "reference_video"]

#: 上集已提交剧本的读取器：入参为上集集号（``episode - 1``），返回该集剧本 dict；剧本不存在 /
#: 未提交时返回 None。取值须为已跑过存量迁移的只读剧本（如
#: ``ProjectManager.load_script_readonly``），供 :func:`previous_episode_exit_state` 抽取上集
#: 末场退出态——这是唯一需要磁盘 IO 的 script_plan prompt 输入，因此不像其余输入那样能由
#: ``project_script_plan_prompt_inputs`` 纯函数自行算出，须由调用方注入读取器。
PreviousScriptLoader = Callable[[int], dict[str, object] | None]


def previous_episode_script_relpath(project: Mapping[str, object], previous_episode: int) -> str:
    """上集剧本相对项目根路径：单一真相源，供每条读取上集剧本的调用方共用同一份解析结果。

    优先取分集账本登记的 ``script_file``（用户可能改过默认落点）；条目缺失该字段（旧式条目）
    或整个账本条目都不存在时回退规范路径 ``lib.episode_paths.episode_script_relpath``。
    ``lib.artifact_planner``（基线预检）与 ``server.text_generation``（生成 / 草稿读时重判）
    都经本函数解析，确保同一上集剧本身份在两条路径上一致——否则两边算出的 basis 会各自认一份
    不同的「上集剧本」，即便都启用了退出态也可能对不上号。
    """

    episodes = project.get("episodes")
    if isinstance(episodes, list):
        for entry in episodes:
            if isinstance(entry, Mapping) and entry.get("episode") == previous_episode:
                script_file = entry.get("script_file")
                if isinstance(script_file, str) and script_file:
                    return script_file
                break
    return episode_script_relpath(previous_episode)


def decode_script_plan_source(raw: bytes) -> str:
    """Decode episode source bytes into the text the script_plan tools consume.

    Script_plan generation reads the source through ``Path.read_text`` and the
    basis freezes that text, so canonical basis reconstruction must apply the
    same universal-newline translation: ``\\r\\n`` and lone ``\\r`` both become
    ``\\n``.  Otherwise a source written with platform line endings never
    matches its registered basis and the script_plan reads stale forever.
    """

    return normalize_newlines(raw.decode("utf-8"))


def build_script_plan_basis(
    source_content: object,
    *,
    episode: int,
    project: Mapping[str, object],
    previous_script_loader: PreviousScriptLoader | None = None,
) -> ArtifactBasis:
    """Describe every durable prompt input consumed by one script_plan artifact."""

    content_mode, generation_mode = _content_axes(project)
    prompt_inputs = project_script_plan_prompt_inputs(
        episode,
        project=project,
        previous_script_loader=previous_script_loader,
    )
    return _build_script_plan_basis(
        source_content,
        content_mode=content_mode,
        generation_mode=generation_mode,
        prompt_inputs=prompt_inputs,
    )


def build_script_plan_request(
    source_content: object,
    *,
    episode: int,
    project: Mapping[str, object],
    expected_variant: ScriptPlanPromptVariant,
    previous_script_loader: PreviousScriptLoader | None = None,
) -> tuple[dict[str, object], ArtifactBasis]:
    """Freeze the prompt projection and basis for one route-specific script_plan request."""

    content_mode, generation_mode = _content_axes(project)
    prompt_inputs = project_script_plan_prompt_inputs(
        episode,
        project=project,
        expected_variant=expected_variant,
        previous_script_loader=previous_script_loader,
    )
    basis = _build_script_plan_basis(
        source_content,
        content_mode=content_mode,
        generation_mode=generation_mode,
        prompt_inputs=prompt_inputs,
    )
    return prompt_inputs, basis


#: 脚本规划 basis 的 kind，以及它作为剧本 basis 输入时的键名。两个值都参与 digest 计算，而落盘
#: 的 ``.arcreel_artifacts.json`` 只留 digest、不留输入，改值便无从重算：存量脚本规划与剧本产物
#: 会整体判成 stale 并阻断下游生成。**值是持久化格式，与 manifest digest 兼容，不得随术语改名。**
SCRIPT_PLAN_BASIS_KIND = "structured-content/step1"
SCRIPT_PLAN_BASIS_INPUT_KEY = "step1_content"


def _build_script_plan_basis(
    source_content: object,
    *,
    content_mode: str,
    generation_mode: str,
    prompt_inputs: Mapping[str, object],
) -> ArtifactBasis:
    return ArtifactBasis.build(
        SCRIPT_PLAN_BASIS_KIND,
        kind_version=2,
        inputs={
            "content_mode": content_mode,
            "generation_mode": generation_mode,
            "source_content": source_content,
            "prompt_context": _freeze_script_plan_prompt_inputs(prompt_inputs, generation_mode=generation_mode),
        },
    )


def project_script_plan_prompt_inputs(
    episode: int,
    *,
    project: Mapping[str, object],
    expected_variant: ScriptPlanPromptVariant | None = None,
    previous_script_loader: PreviousScriptLoader | None = None,
) -> dict[str, object]:
    """Project persisted fields passed to the selected script_plan prompt builder.

    Capability tiers and one-shot instructions are execution inputs and stay out
    of this projection. Asset mappings preserve insertion order because all
    three prompt builders render that order verbatim.

    ``previous_script_loader``（drama 变体，第二集起）供 :func:`lib.episode_ledger.
    previous_episode_exit_state` 抽取上集末场的退出态：本函数本身不做磁盘 IO，缺省时该输入
    静默省略（与「无上集」同效——不影响其余输入的投影）。
    """

    if type(episode) is not int or episode < 1:
        raise ValueError("episode must be a positive integer")
    content_mode, generation_mode = _content_axes(project)
    variant = _script_plan_prompt_variant(content_mode, generation_mode)
    if expected_variant is not None and variant != expected_variant:
        raise ValueError(
            f"{expected_variant} script_plan is unavailable for "
            f"content_mode={content_mode!r}, generation_mode={generation_mode!r}"
        )
    overview = _mapping_or_empty(project.get("overview"))
    source_language = project.get("source_language") or _DEFAULT_SOURCE_LANGUAGE
    if not isinstance(source_language, str):
        raise ValueError(f"source_language must be a non-empty string or null, got {source_language!r}")

    inputs: dict[str, object] = {
        "episode": episode,
        "project_overview": {field: overview.get(field, "") for field in (*_AD_OVERVIEW_FIELDS, "world_setting")},
        "characters": _project_script_plan_asset_mapping(project.get("characters")),
        "scenes": _project_script_plan_asset_mapping(project.get("scenes")),
        "props": _project_script_plan_asset_mapping(project.get("props")),
        "target_language": source_language,
        # 单集目标时长是项目持久化偏好、三条 script_plan 变体共用：设了目标就进 basis，改它
        # 即让冻结的产出基线失效，因为它改变了下发给模型的拆分口径。未设时为 None，
        # 由 _freeze_script_plan_prompt_inputs 剔出 basis（提示词此时与不带该参数时相同）。
        "episode_target_duration": project_episode_target_duration(project),
    }

    if variant in {"reference_video", "drama"}:
        episode_outline, next_episode_outline = episode_outline_context(project, episode)
        inputs.update(
            {
                "episode_outline": episode_outline,
                "next_episode_outline": next_episode_outline,
            }
        )
        # 上集大纲只在存在时进 basis：首集与上集无规划数据时提示词逐字不变，不能让存量
        # 项目的脚本规划产物因新增一个恒为 None 的键而判 stale。
        previous_episode_outline = previous_episode_outline_context(project, episode)
        if previous_episode_outline is not None:
            inputs["previous_episode_outline"] = previous_episode_outline

    if variant == "drama" and episode > 1 and previous_script_loader is not None:
        # 退出态是事实性快照（见 previous_episode_exit_state docstring），只在存在时进 basis——
        # 首集、上集未提交剧本、或上集末场字段皆空时提示词逐字不变，与 previous_episode_outline
        # 同一「未设不进 basis」口径。
        exit_state = previous_episode_exit_state(previous_script_loader(episode - 1))
        if exit_state is not None:
            inputs["previous_episode_exit_state"] = exit_state

    if variant in {"reference_video", "drama"}:
        raw_source_language = project.get("source_language")
        inputs.update(
            {
                "source_language": raw_source_language if isinstance(raw_source_language, str) else None,
                "speech_rate_override": project_speech_rate_override(project),
            }
        )

    if variant == "drama":
        raw_source_kind = project.get("source_kind")
        source_kind = "novel" if raw_source_kind is None else raw_source_kind
        if not isinstance(source_kind, str) or source_kind not in _SOURCE_KINDS:
            raise ValueError(f"unsupported source_kind: {source_kind!r}")
        inputs.update(
            {
                "source_kind": source_kind,
                "style": _optional_string(project.get("style"), "style"),
                # 受众 gear（目前只有儿童档位）只在 drama 用到；未设受众时为 None，
                # 由 _freeze_script_plan_prompt_inputs 剔出 basis（此时 prompt 与不带该参数时逐字相同）。
                "audience": resolve_project_audience_text(project),
            }
        )

    return inputs


def _freeze_script_plan_prompt_inputs(
    prompt_inputs: Mapping[str, object],
    *,
    generation_mode: str,
) -> dict[str, object]:
    """Convert runtime prompt mappings into an order-sensitive JSON basis."""

    frozen = dict(prompt_inputs)
    for field in ("characters", "scenes", "props"):
        raw_assets = _mapping_or_empty(prompt_inputs.get(field))
        if generation_mode == "reference_video":
            frozen[field] = [
                {
                    "name": name,
                    "description": (raw.get("description", "") if isinstance(raw, Mapping) else ""),
                }
                for name, raw in raw_assets.items()
            ]
        else:
            frozen[field] = list(raw_assets)

    if "source_language" in frozen:
        source_language = frozen.pop("source_language")
        source_language = source_language if isinstance(source_language, str) else None
        speech_rate_override = frozen.pop("speech_rate_override", None)
        speech_rate_override = speech_rate_override if isinstance(speech_rate_override, (int, float)) else None
        frozen["speech_rate_units_per_second"] = speech_rate_units_per_second(
            source_language,
            speech_rate_override,
        )
        frozen["reading_unit_noun"] = reading_unit_noun(source_language)

    if generation_mode == "reference_video":
        for field in ("episode_outline", "next_episode_outline"):
            frozen[field] = _freeze_reference_outline(prompt_inputs.get(field))
        if "previous_episode_outline" in frozen:
            frozen["previous_episode_outline"] = _freeze_reference_outline(
                prompt_inputs.get("previous_episode_outline")
            )

    if "previous_episode_exit_state" in frozen:
        frozen_exit_state = _freeze_previous_episode_exit_state(frozen["previous_episode_exit_state"])
        if frozen_exit_state is None:
            frozen.pop("previous_episode_exit_state", None)
        else:
            frozen["previous_episode_exit_state"] = frozen_exit_state

    # 未设单集目标时长时该键不进 basis：此时提示词与不带该参数时逐字相同，把 None 写进
    # digest 会让每个从未用过该设置的存量项目的脚本规划与剧本产物一并判 stale。设了目标
    # 才进 basis——那时提示词确实变了，冻结的基线就该失效。
    if frozen.get("episode_target_duration") is None:
        frozen.pop("episode_target_duration", None)
    # 未设受众时同一口径剔出 basis：此时受众 gear 不渲染，prompt 与不带该参数时逐字相同，
    # 把 None 写进 digest 会让每个从未设置过 audience 的存量项目的脚本规划产物一并判 stale。
    if frozen.get("audience") is None:
        frozen.pop("audience", None)
    return frozen


def _freeze_reference_outline(value: object) -> dict[str, object] | None:
    """Match the reference-video outline renderer's whitespace semantics."""

    if not isinstance(value, Mapping):
        return None
    result: dict[str, object] = {}
    for field in ("title", "hook", "next_episode_teaser"):
        raw = value.get(field)
        if isinstance(raw, str) and raw.strip():
            result[field] = raw.strip()
    raw_beats = value.get("story_beats")
    if isinstance(raw_beats, list):
        beats = [beat for beat in raw_beats if isinstance(beat, str) and beat.strip()]
        if beats:
            result["story_beats"] = beats
    return result or None


def _freeze_previous_episode_exit_state(value: object) -> dict[str, object] | None:
    """Trim whitespace / drop empties the same way :func:`_freeze_reference_outline` does.

    上集末场退出态是事实性快照，改动上集剧本末场即让本集 script_plan 判 stale——这是有意为之
    （见 ``lib.episode_ledger.previous_episode_exit_state`` docstring），本函数只负责去掉不影响
    渲染结果的空白差异，不改变「上集末场变了就该 stale」这条判据。
    """

    if not isinstance(value, Mapping):
        return None
    result: dict[str, object] = {}
    raw_scene_id = value.get("scene_id")
    if isinstance(raw_scene_id, str) and raw_scene_id.strip():
        result["scene_id"] = raw_scene_id.strip()
    for field in ("location", "characters_present", "props"):
        raw_list = value.get(field)
        if isinstance(raw_list, list):
            items = [item.strip() for item in raw_list if isinstance(item, str) and item.strip()]
            if items:
                result[field] = items
    raw_last_action = value.get("last_action")
    if isinstance(raw_last_action, str) and raw_last_action.strip():
        result["last_action"] = raw_last_action.strip()
    raw_last_utterance = value.get("last_utterance")
    if isinstance(raw_last_utterance, Mapping):
        text = raw_last_utterance.get("text")
        if isinstance(text, str) and text.strip():
            speaker = raw_last_utterance.get("speaker")
            result["last_utterance"] = {
                "speaker": speaker.strip() if isinstance(speaker, str) and speaker.strip() else None,
                "text": text.strip(),
            }
    return result or None


def _script_plan_prompt_variant(content_mode: str, generation_mode: str) -> ScriptPlanPromptVariant:
    if generation_mode == "reference_video":
        return "reference_video"
    if content_mode == "drama":
        return "drama"
    return "narration"


def build_episode_script_basis(script_plan_content: object, *, project: Mapping[str, object]) -> ArtifactBasis:
    """Describe every durable prompt input consumed by an episode script."""

    content_mode, generation_mode = _content_axes(project)
    return ArtifactBasis.build(
        "structured-content/episode-script",
        kind_version=2,
        inputs={
            "content_mode": content_mode,
            "generation_mode": generation_mode,
            SCRIPT_PLAN_BASIS_INPUT_KEY: script_plan_content,
            "prompt_context": project_episode_script_prompt_inputs(project),
        },
    )


def build_planless_episode_script_basis(episode: int) -> ArtifactBasis:
    """Describe an episode script that has no formal script_plan to depend on.

    The basis names only the episode, so the script stays current until a formal
    plan appears and the regular basis takes over.
    """

    if type(episode) is not int or episode < 1:
        raise ValueError("episode must be a positive integer")
    return ArtifactBasis.build(
        "structured-content/episode-script-without-plan",
        kind_version=1,
        inputs={"episode": episode},
    )


def project_episode_script_prompt_inputs(project: Mapping[str, object]) -> dict[str, object]:
    """Project the persisted project fields rendered into non-ad prompt_authoring prompts.

    Provider/model capabilities and one-shot user instructions are execution
    inputs, not durable project state. Asset order is retained because the
    prompt renders mappings in insertion order; changing that order changes the
    exact provider input even though JSON object equality would not.
    """

    content_mode, generation_mode = _content_axes(project)
    overview = _mapping_or_empty(project.get("overview"))
    aspect_ratio = project.get("aspect_ratio")
    if not isinstance(aspect_ratio, str):
        aspect_ratio = "9:16" if content_mode == "narration" else "16:9"
    target_language = project.get("source_language") or _DEFAULT_SOURCE_LANGUAGE
    if not isinstance(target_language, str):
        raise ValueError("episode script source_language must be a string or null")

    inputs: dict[str, object] = {
        "overview": {field: overview.get(field, "") for field in (*_AD_OVERVIEW_FIELDS, "world_setting")},
        "style": _optional_string(project.get("style"), "style"),
        "style_description": _optional_string(project.get("style_description"), "style_description"),
        "aspect_ratio": aspect_ratio,
        "target_language": target_language,
        "characters": _project_prompt_authoring_assets(project.get("characters"), generation_mode=generation_mode),
        "scenes": _project_prompt_authoring_assets(project.get("scenes"), generation_mode=generation_mode),
        "props": _project_prompt_authoring_assets(project.get("props"), generation_mode=generation_mode),
    }
    if content_mode == "drama":
        # 受众 gear 只在 drama prompt_authoring 用到（narration / reference_video 未接入）；
        # 只在设了受众时进 basis，未设时不改变从未用过该设置的存量项目的 digest。
        audience = resolve_project_audience_text(project)
        if audience is not None:
            inputs["audience"] = audience
    return inputs


def build_ad_episode_script_basis(episode: int, *, project: Mapping[str, object]) -> ArtifactBasis:
    """Describe the persisted business inputs consumed by ad script generation."""

    inputs = project_ad_episode_script_inputs(episode, project=project)
    return ArtifactBasis.build(
        "structured-content/ad-episode-script",
        kind_version=2,
        inputs=_freeze_ad_prompt_table_order(inputs),
    )


def project_ad_episode_script_inputs(
    episode: int,
    *,
    project: Mapping[str, object],
) -> dict[str, object]:
    """Project exactly the durable ad inputs shared by prompt and provenance."""

    if type(episode) is not int or episode < 1:
        raise ValueError("episode must be a positive integer")
    if project.get("content_mode") != "ad":
        raise ValueError("ad episode script basis requires content_mode='ad'")
    generation_mode = project.get("generation_mode")
    if not isinstance(generation_mode, str) or generation_mode not in _GENERATION_MODES:
        raise ValueError(f"unsupported generation_mode: {generation_mode!r}")
    target_duration = project.get("target_duration")
    if type(target_duration) is not int or target_duration <= 0:
        raise ValueError("ad target_duration must be a positive integer")

    overview = _mapping_or_empty(project.get("overview"))
    overview_fields = (
        (*_AD_OVERVIEW_FIELDS, "world_setting") if generation_mode == "storyboard" else _AD_OVERVIEW_FIELDS
    )
    projected_overview = {field: overview.get(field, "") for field in overview_fields}
    target_language = project.get("source_language") or _DEFAULT_SOURCE_LANGUAGE
    if not isinstance(target_language, str):
        raise ValueError("ad source_language must be a string or null")

    inputs: dict[str, object] = {
        "content_mode": "ad",
        "generation_mode": generation_mode,
        "episode": episode,
        "overview": projected_overview,
        "style": _optional_string(project.get("style"), "style"),
        "style_description": _optional_string(project.get("style_description"), "style_description"),
        "characters": _project_named_assets(project.get("characters")),
        "scenes": _project_named_assets(project.get("scenes")),
        "props": _project_named_assets(project.get("props")),
        "products": _project_products(project.get("products")),
        "brief": _optional_string(project.get("brief"), "brief"),
        "target_duration": target_duration,
        "aspect_ratio": project.get("aspect_ratio") if isinstance(project.get("aspect_ratio"), str) else "9:16",
        "target_language": target_language,
    }
    if generation_mode == "storyboard":
        inputs["speech_rate_override"] = project_speech_rate_override(project)
    return inputs


def _mapping_or_empty(value: object) -> Mapping[object, object]:
    return value if isinstance(value, Mapping) else {}


def _optional_string(value: object, field: str) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError(f"ad {field} must be a string or null")
    return value


def _freeze_ad_prompt_table_order(inputs: Mapping[str, object]) -> dict[str, object]:
    """Encode prompt-rendered mapping order explicitly for canonical JSON."""

    frozen = dict(inputs)
    for field in ("characters", "scenes", "props", "products"):
        frozen[field] = [{"name": name, "value": value} for name, value in _mapping_or_empty(inputs.get(field)).items()]
    return frozen


def _project_named_assets(value: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in _mapping_or_empty(value):
        if not isinstance(name, str):
            raise ValueError("ad asset names must be strings")
        result[name] = {}
    return result


def _project_script_plan_asset_mapping(value: object) -> dict[str, object]:
    """Copy the ordered asset table rendered by script_plan prompt builders."""

    result: dict[str, object] = {}
    for name, raw in _mapping_or_empty(value).items():
        if not isinstance(name, str):
            raise ValueError("script_plan asset names must be strings")
        result[name] = dict(raw) if isinstance(raw, Mapping) else {}
    return result


def _project_prompt_authoring_assets(value: object, *, generation_mode: str) -> list[dict[str, object]]:
    """Project the ordered name/description pairs rendered by prompt_authoring builders."""

    result: list[dict[str, object]] = []
    for raw_name, raw in _mapping_or_empty(value).items():
        if not isinstance(raw_name, str):
            raise ValueError("episode script asset names must be strings")
        data = raw if isinstance(raw, Mapping) else {}
        description = data.get("description")
        if generation_mode == "reference_video":
            rendered_description: object = description if "description" in data else ""
        else:
            rendered_description = description.strip() if isinstance(description, str) and description.strip() else ""
        result.append({"name": raw_name, "description": rendered_description})
    return result


def _project_products(value: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, raw in _mapping_or_empty(value).items():
        if not isinstance(name, str):
            raise ValueError("ad product names must be strings")
        data = raw if isinstance(raw, Mapping) else {}
        product: dict[str, object] = {}
        for field in ("brand", "description"):
            item = data.get(field)
            if item:
                if not isinstance(item, str):
                    raise ValueError(f"ad product {field} must be a string")
                product[field] = item
        raw_points = data.get("selling_points")
        if isinstance(raw_points, list):
            points = [point for point in raw_points if isinstance(point, str) and point.strip()]
            if points:
                product["selling_points"] = points
        result[name] = product
    return result


def _content_axes(project: Mapping[str, object]) -> tuple[str, str]:
    content_mode = project.get("content_mode")
    if not isinstance(content_mode, str) or content_mode not in _STRUCTURED_CONTENT_MODES:
        raise ValueError(f"structured content basis does not support content_mode: {content_mode!r}")
    generation_mode = project.get("generation_mode")
    if not isinstance(generation_mode, str) or generation_mode not in _GENERATION_MODES:
        raise ValueError(f"unsupported generation_mode: {generation_mode!r}")
    return content_mode, generation_mode
