"""Tests for SkillRegistry — discover, lookup, and filter pipeline skills."""
from __future__ import annotations

from pathlib import Path

import pytest

from news_sentry.core.skill_registry import SkillRegistry, discover_skills
from news_sentry.models.manifests import RuntimeCompatibility, SkillManifest

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """创建模拟 skills 目录，含 collect / filter / judge / output 四个子目录。"""
    skills_root = tmp_path / "skills"
    stages = {
        "collect": "Collect skills — RSS, API, and OpenCLI-based news collection.",
        "filter": "Filter skills — rule-based filtering and classification of NewsEvents.",
        "judge": "Judge skills — AI-powered news value judgement.",
        "output": "Output skills — Markdown and other output format writers.",
    }
    for stage, doc in stages.items():
        stage_dir = skills_root / stage
        stage_dir.mkdir(parents=True)
        init = stage_dir / "__init__.py"
        init.write_text(f'"""{doc}"""\n', encoding="utf-8")
    return skills_root


# ──────────────────────────────────────────────────────────────
# discover_skills (module-level function)
# ──────────────────────────────────────────────────────────────


class TestDiscoverSkills:
    """discover_skills() 函数测试。"""

    def test_discovers_all_stages(self, skills_dir: Path) -> None:
        result = discover_skills(skills_dir)
        assert set(result.keys()) == {"collect", "filter", "judge", "output"}

    def test_each_has_stage_field(self, skills_dir: Path) -> None:
        result = discover_skills(skills_dir)
        for skill_id, manifest in result.items():
            assert manifest.stage == skill_id

    def test_each_has_runtime_compatibility(self, skills_dir: Path) -> None:
        result = discover_skills(skills_dir)
        for manifest in result.values():
            assert RuntimeCompatibility.CLI in manifest.runtime_compatibility
            assert RuntimeCompatibility.HERMES in manifest.runtime_compatibility
            assert RuntimeCompatibility.OPENCLAW in manifest.runtime_compatibility

    def test_each_has_entry_point(self, skills_dir: Path) -> None:
        result = discover_skills(skills_dir)
        for manifest in result.values():
            assert manifest.entry_point == f"news_sentry.skills.{manifest.stage}"

    def test_uses_docstring_as_display_name(self, skills_dir: Path) -> None:
        result = discover_skills(skills_dir)
        assert result["collect"].display_name == (
            "Collect skills — RSS, API, and OpenCLI-based news collection."
        )

    def test_missing_init_skipped(self, tmp_path: Path) -> None:
        """没有 __init__.py 的子目录应被跳过。"""
        skills_root = tmp_path / "skills"
        (skills_root / "empty").mkdir(parents=True)
        result = discover_skills(skills_root)
        assert "empty" not in result

    def test_underscore_dirs_skipped(self, skills_dir: Path) -> None:
        """以下划线开头的目录应被跳过。"""
        hidden = skills_dir / "__pycache__"
        hidden.mkdir(exist_ok=True)
        (hidden / "__init__.py").write_text('"""cache"""\n', encoding="utf-8")
        result = discover_skills(skills_dir)
        assert "__pycache__" not in result

    def test_empty_skills_dir(self, tmp_path: Path) -> None:
        """空目录返回空字典。"""
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        result = discover_skills(empty)
        assert result == {}

    def test_not_a_directory(self, tmp_path: Path) -> None:
        """传入不存在的路径返回空字典。"""
        result = discover_skills(tmp_path / "nonesuch")
        assert result == {}

    def test_extract_doc_unreadable_file(self, tmp_path: Path) -> None:
        """_extract_first_doc_line 读取失败时返回空字符串。"""
        from news_sentry.core.skill_registry import _extract_first_doc_line

        bad_file = tmp_path / "bad.py"
        bad_file.write_text("not valid python {", encoding="utf-8")
        result = _extract_first_doc_line(bad_file)
        assert result == ""

    def test_extract_doc_no_docstring(self, tmp_path: Path) -> None:
        """_extract_first_doc_line 模块无 docstring 时返回空字符串。"""
        from news_sentry.core.skill_registry import _extract_first_doc_line

        no_doc = tmp_path / "nodoc.py"
        no_doc.write_text("x = 1\n", encoding="utf-8")
        result = _extract_first_doc_line(no_doc)
        assert result == ""

    def test_extract_doc_returns_first_line(self, tmp_path: Path) -> None:
        """_extract_first_doc_line 只返回 docstring 第一行。"""
        from news_sentry.core.skill_registry import _extract_first_doc_line

        multi = tmp_path / "multi.py"
        multi.write_text('"""First line\nSecond line\nThird line"""\n', encoding="utf-8")
        result = _extract_first_doc_line(multi)
        assert result == "First line"

    def test_dot_dirs_skipped(self, skills_dir: Path) -> None:
        """以点开头的目录应被跳过。"""
        dot = skills_dir / ".hidden"
        dot.mkdir()
        (dot / "__init__.py").write_text('"""hidden"""\n', encoding="utf-8")
        result = discover_skills(skills_dir)
        assert ".hidden" not in result

    def test_no_docstring_uses_stage_as_display_name(self, tmp_path: Path) -> None:
        """模块无 docstring 时 display_name 退化为 stage 名。"""
        skills_root = tmp_path / "skills"
        stage_dir = skills_root / "mystage"
        stage_dir.mkdir(parents=True)
        (stage_dir / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        result = discover_skills(skills_root)
        assert result["mystage"].display_name == "mystage"


# ──────────────────────────────────────────────────────────────
# SkillRegistry class
# ──────────────────────────────────────────────────────────────


class TestSkillRegistry:
    """SkillRegistry 方法测试。"""

    @pytest.fixture
    def registry(self, skills_dir: Path) -> SkillRegistry:
        return SkillRegistry(skills_dir)

    def test_get_skill_returns_manifest(self, registry: SkillRegistry) -> None:
        m = registry.get_skill("collect")
        assert isinstance(m, SkillManifest)
        assert m.skill_id == "collect"

    def test_get_skill_unknown_returns_none(self, registry: SkillRegistry) -> None:
        assert registry.get_skill("nonexistent") is None

    def test_list_skills_returns_all(self, registry: SkillRegistry) -> None:
        all_skills = registry.list_skills()
        assert len(all_skills) == 4

    def test_list_skills_by_stage_filters(self, registry: SkillRegistry) -> None:
        collect_skills = registry.list_skills_by_stage("collect")
        assert len(collect_skills) == 1
        assert collect_skills[0].skill_id == "collect"

    def test_list_skills_by_stage_empty_for_unknown(self, registry: SkillRegistry) -> None:
        assert registry.list_skills_by_stage("unknown") == []
