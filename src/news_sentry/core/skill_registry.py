"""Phase 4: SkillManifest Registry — discovers and manages pipeline skills."""

from __future__ import annotations

import ast
from pathlib import Path

from news_sentry.models.manifests import RuntimeCompatibility, SkillManifest


def _extract_first_doc_line(filepath: Path) -> str:
    """提取 Python 模块 docstring 的第一行，或返回空字符串。"""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return ""
    try:
        tree = ast.parse(text)
        doc = ast.get_docstring(tree)
        if doc:
            return doc.strip().split("\n")[0]
    except SyntaxError:
        pass
    return ""


def discover_skills(skills_dir: Path) -> dict[str, SkillManifest]:
    """遍历 skills_dir 子目录，为每个含 __init__.py 的子目录构建 SkillManifest。

    Args:
        skills_dir: src/news_sentry/skills/ 目录路径。

    Returns:
        skill_id -> SkillManifest 映射字典。
    """
    manifests: dict[str, SkillManifest] = {}
    if not skills_dir.is_dir():
        return manifests

    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_") or child.name.startswith("."):
            continue
        init_file = child / "__init__.py"
        if not init_file.is_file():
            continue

        stage = child.name
        display_name = _extract_first_doc_line(init_file) or stage

        manifest = SkillManifest(
            skill_id=stage,
            display_name=display_name,
            version="1.0.0",
            stage=stage,
            entry_point=f"news_sentry.skills.{stage}",
            runtime_compatibility=[
                RuntimeCompatibility.CLI,
            ],
        )
        manifests[stage] = manifest

    return manifests


class SkillRegistry:
    """SkillManifest 注册中心 — 管理 pipeline 技能的发现与查询。"""

    def __init__(self, skills_dir: Path) -> None:
        self._skills: dict[str, SkillManifest] = discover_skills(skills_dir)

    def get_skill(self, skill_id: str) -> SkillManifest | None:
        """按 skill_id 查找技能。"""
        return self._skills.get(skill_id)

    def list_skills(self) -> list[SkillManifest]:
        """返回所有已注册技能。"""
        return list(self._skills.values())

    def list_skills_by_stage(self, stage: str) -> list[SkillManifest]:
        """按 pipeline 阶段过滤技能。"""
        return [s for s in self._skills.values() if s.stage == stage]
