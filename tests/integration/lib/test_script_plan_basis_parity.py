"""script_plan basis 计算的三条路径（生成 / 草稿读时重判 / 基线预检）须对同一上集剧本状态给出
同一个 digest——否则生成时纳入的上集末场退出态（``previous_episode_exit_state``）在重判 / 预检
时被当作不存在，episode ≥2 的 drama script_plan 会在刚生成完之后就被判 stale 或重判失败。

三条路径共用同一个上集剧本文件名解析（``lib.artifact_provenance.previous_episode_script_relpath``）
与同一个 basis 计算入口（``lib.artifact_provenance.build_script_plan_basis`` /
``build_script_plan_request``），本测试端到端跑通三条路径并断言 digest 一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.artifact_planner import TargetStatePlanner
from lib.artifact_provenance import build_script_plan_basis, decode_script_plan_source
from lib.draft_quarantine import QUARANTINE_KIND_DRAMA_SCRIPT_PLAN, QuarantinedDraft
from lib.project_manager import ProjectManager
from server.draft_workflow import revalidate_drama_script_plan_draft
from server.text_generation import _load_script_plan_source_with_basis

PROJECT_NAME = "proj1"

_EPISODE_1_SCRIPT = {
    "content_mode": "drama",
    "episode": 1,
    "scenes": [
        {"scene_id": "E1S01", "scenes": ["村口"], "characters_in_scene": ["张三"]},
        {
            "scene_id": "E1S02",
            "scenes": ["山洞"],
            "characters_in_scene": ["张三", "李四"],
            "props": ["火把"],
            "utterances": [{"kind": "dialogue", "speaker": "张三", "text": "我们到了。"}],
            "video_prompt": {
                "action": "张三举起火把环顾四周",
                "camera_motion": "Static",
                "ambiance_audio": "风声",
            },
        },
    ],
}


def _write_project(root: Path) -> Path:
    project_dir = root / PROJECT_NAME
    (project_dir / "source").mkdir(parents=True)
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "source" / "episode_2.txt").write_text("次日，山下。", encoding="utf-8")
    (project_dir / "scripts" / "episode_1.json").write_text(
        json.dumps(_EPISODE_1_SCRIPT, ensure_ascii=False), encoding="utf-8"
    )
    project = {
        "content_mode": "drama",
        "generation_mode": "storyboard",
        "source_kind": "novel",
        "source_language": "中文",
        "overview": {},
        "characters": {},
        "scenes": {},
        "props": {},
        "style": "anime",
        "episodes": [
            {"episode": 1, "script_file": "scripts/episode_1.json"},
            {"episode": 2, "script_file": "scripts/episode_2.json"},
        ],
    }
    (project_dir / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    return project_dir


async def test_generation_revalidation_and_planner_bases_agree_on_the_previous_episode_exit_state(
    tmp_path: Path,
) -> None:
    """生成 / 草稿读时重判 / 基线预检三条路径对第二集 script_plan 的 basis digest 必须一致。"""

    project_dir = _write_project(tmp_path)
    pm = ProjectManager(str(tmp_path))
    project = pm.load_project_readonly(PROJECT_NAME)

    # 生成路径：server.text_generation 的 script_plan 请求装配。
    _novel_text, _prompt_inputs, generation_basis = _load_script_plan_source_with_basis(
        project_dir,
        None,
        project,
        2,
        "drama",
        projects=pm,
        project_name=PROJECT_NAME,
    )

    # 草稿读时重判路径：与晋升工具、内容确认共用的同一个重判器。草稿内容故意留空触发
    # schema_failed，但 basis 在 schema 校验之前就已经算好并原样返回。
    draft = QuarantinedDraft(
        kind=QUARANTINE_KIND_DRAMA_SCRIPT_PLAN,
        episode=2,
        content={},
        violations=[],
        meta={"source": None},
        schema_version=1,
        path=project_dir / "drafts" / "episode_2" / "script_plan_normalized_script.invalid.json",
    )
    revalidation = await revalidate_drama_script_plan_draft(
        project_dir,
        project,
        2,
        draft,
        projects=pm,
        project_name=PROJECT_NAME,
    )
    assert revalidation.basis is not None
    revalidation_basis = revalidation.basis

    # 基线预检路径：lib.artifact_planner 的目标态规划重建同一个 basis（与
    # ``TargetStatePlanner._plan_one_script_plan`` 同一个 loader 方法）。
    planner = TargetStatePlanner(project_dir)
    source_raw = (project_dir / "source" / "episode_2.txt").read_bytes()
    source_content = decode_script_plan_source(source_raw)
    planner_basis = build_script_plan_basis(
        source_content,
        episode=2,
        project=planner.project,
        previous_script_loader=planner._previous_script_loader(),
    )

    assert generation_basis.digest == revalidation_basis.digest
    assert generation_basis.digest == planner_basis.digest

    # 反证：不带上集剧本读取器时 digest 不同——证明前三者确实纳入了退出态，parity 不是因为
    # 退出态从未参与计算而巧合相等。
    basis_without_exit_state = build_script_plan_basis(source_content, episode=2, project=project)
    assert basis_without_exit_state.digest != generation_basis.digest


async def test_planner_basis_matches_generation_when_previous_script_is_absent(tmp_path: Path) -> None:
    """上集剧本缺失（尚未生成）时三条路径同样一致：退出态静默省略，不进 basis。"""

    project_dir = _write_project(tmp_path)
    (project_dir / "scripts" / "episode_1.json").unlink()
    pm = ProjectManager(str(tmp_path))
    project = pm.load_project_readonly(PROJECT_NAME)

    _novel_text, _prompt_inputs, generation_basis = _load_script_plan_source_with_basis(
        project_dir,
        None,
        project,
        2,
        "drama",
        projects=pm,
        project_name=PROJECT_NAME,
    )

    planner = TargetStatePlanner(project_dir)
    source_raw = (project_dir / "source" / "episode_2.txt").read_bytes()
    source_content = decode_script_plan_source(source_raw)
    planner_basis = build_script_plan_basis(
        source_content,
        episode=2,
        project=planner.project,
        previous_script_loader=planner._previous_script_loader(),
    )
    basis_without_loader = build_script_plan_basis(source_content, episode=2, project=project)

    assert generation_basis.digest == planner_basis.digest == basis_without_loader.digest


if __name__ == "__main__":
    pytest.main([__file__])
