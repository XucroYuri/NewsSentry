"""Tests for adapter_health — pre-run validation of tools and skills."""
from __future__ import annotations

from pathlib import Path

import pytest

from news_sentry.core.adapter_health import check_all_adapters
from news_sentry.core.skill_registry import SkillRegistry
from news_sentry.core.tool_registry import ToolRegistry

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """创建模拟 skills 目录。"""
    skills_root = tmp_path / "skills"
    for stage in ["collect", "filter"]:
        stage_dir = skills_root / stage
        stage_dir.mkdir(parents=True)
        (stage_dir / "__init__.py").write_text(f'"""{stage} skill"""\n', encoding="utf-8")
    return skills_root


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    """创建模拟 toolmanifest 目录。"""
    import yaml

    d = tmp_path / "toolmanifest"
    d.mkdir()
    manifest = {
        "tools": [
            {
                "tool_id": "opencli.echo",
                "display_name": "Echo Test",
                "version": "1.0.0",
                "execution_type": "subprocess",
                "command_template": "echo hello",
                "exit_codes": {"0": "success"},
                "permissions": {"risk_level": "low"},
            },
        ]
    }
    (d / "test.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    return d


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────


class TestCheckAllAdapters:
    """check_all_adapters() 测试。"""

    def test_returns_list(self, manifest_dir: Path, skills_dir: Path) -> None:
        tr = ToolRegistry(manifest_dir)
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(tr, sr)
        assert isinstance(results, list)

    def test_includes_skills_and_tools(self, manifest_dir: Path, skills_dir: Path) -> None:
        tr = ToolRegistry(manifest_dir)
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(tr, sr)
        # 2 skills + 1 tool = 3 results
        assert len(results) == 3
        names = [r["name"] for r in results]
        assert any("Skill:" in n for n in names)
        assert any("Tool:" in n for n in names)

    def test_each_result_has_required_fields(self, manifest_dir: Path, skills_dir: Path) -> None:
        tr = ToolRegistry(manifest_dir)
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(tr, sr)
        for r in results:
            assert "name" in r
            assert "ok" in r
            assert "severity" in r
            assert "message" in r

    def test_skill_with_valid_entry_point_ok(self, manifest_dir: Path, skills_dir: Path) -> None:
        tr = ToolRegistry(manifest_dir)
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(tr, sr)
        skill_results = [r for r in results if r["name"].startswith("Skill:")]
        # 实际 skills 目录中的模块应该可导入
        for sr_item in skill_results:
            assert "news_sentry.skills" in str(sr_item["message"])

    def test_skill_missing_entry_point(self, manifest_dir: Path, tmp_path: Path) -> None:
        """entry_point 不存在时报告 warning。"""

        tr = ToolRegistry(manifest_dir)

        # 手动构造一个含不存在模块的 SkillManifest
        broken_skills_dir = tmp_path / "broken_skills"
        broken_skills_dir.mkdir()
        broken_stage = broken_skills_dir / "broken"
        broken_stage.mkdir()
        (broken_stage / "__init__.py").write_text('"""broken"""\n', encoding="utf-8")
        sr = SkillRegistry(broken_skills_dir)
        # 手动覆盖 entry_point 为不存在的模块
        skill = sr.get_skill("broken")
        assert skill is not None
        skill.entry_point = "nonexistent.module.path"

        results = check_all_adapters(tr, sr)
        broken_results = [r for r in results if "broken" in str(r["name"])]
        assert len(broken_results) == 1
        assert broken_results[0]["ok"] is False
        assert broken_results[0]["severity"] == "warning"

    def test_empty_registries(self, tmp_path: Path) -> None:
        """空注册中心返回空结果列表。"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        tr = ToolRegistry(empty_dir)
        sr = SkillRegistry(empty_dir)
        results = check_all_adapters(tr, sr)
        assert results == []
