"""ProjectManager global_assets helper."""

from __future__ import annotations

from lib.project_manager import ProjectManager


def test_get_global_assets_root_creates_subdirs(tmp_path):
    pm = ProjectManager(tmp_path / "projects")
    root = pm.get_global_assets_root()
    assert root == tmp_path / "projects" / "_global_assets"
    for sub in ("character", "scene", "prop"):
        assert (root / sub).is_dir()


def test_list_projects_skips_global_assets(tmp_path):
    pm = ProjectManager(tmp_path / "projects")
    pm.get_global_assets_root()  # 生成 _global_assets
    (pm.projects_root / "my-project").mkdir()
    assert pm.list_projects() == ["my-project"]


def test_list_projects_skips_directories_that_are_not_valid_project_ids(tmp_path):
    # app_data_dir() 默认与 projects 根同目录：trial_runs/ 这类应用数据目录、隐藏目录、
    # 名字含下划线或空格的目录都不是项目，列出来只会得到一张既打不开也删不掉的卡片。
    pm = ProjectManager(tmp_path / "projects")
    for name in ("trial_runs", ".hidden", "with space", "valid-1"):
        (pm.projects_root / name).mkdir(parents=True)
    (pm.projects_root / "a-file.txt").write_text("x")
    assert pm.list_projects() == ["valid-1"]
