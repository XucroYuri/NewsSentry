"""Tests for adapter_health — pre-run validation of skills."""

from __future__ import annotations

from pathlib import Path

import pytest

from news_sentry.core.adapter_health import check_all_adapters
from news_sentry.core.skill_registry import SkillRegistry

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


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────


class TestCheckAllAdapters:
    """check_all_adapters() 测试。"""

    def test_returns_list(self, skills_dir: Path) -> None:
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(sr)
        assert isinstance(results, list)

    def test_includes_skills(self, skills_dir: Path) -> None:
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(sr)
        assert len(results) == 2
        names = [r["name"] for r in results]
        assert all("Skill:" in n for n in names)

    def test_each_result_has_required_fields(self, skills_dir: Path) -> None:
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(sr)
        for r in results:
            assert "name" in r
            assert "ok" in r
            assert "severity" in r
            assert "message" in r

    def test_skill_with_valid_entry_point_ok(self, skills_dir: Path) -> None:
        sr = SkillRegistry(skills_dir)
        results = check_all_adapters(sr)
        skill_results = [r for r in results if r["name"].startswith("Skill:")]
        for sr_item in skill_results:
            assert "news_sentry.skills" in str(sr_item["message"])

    def test_skill_missing_entry_point(self, tmp_path: Path) -> None:
        """entry_point 不存在时报告 warning。"""
        broken_skills_dir = tmp_path / "broken_skills"
        broken_skills_dir.mkdir()
        broken_stage = broken_skills_dir / "broken"
        broken_stage.mkdir()
        (broken_stage / "__init__.py").write_text('"""broken"""\n', encoding="utf-8")
        sr = SkillRegistry(broken_skills_dir)
        skill = sr.get_skill("broken")
        assert skill is not None
        skill.entry_point = "nonexistent.module.path"

        results = check_all_adapters(sr)
        broken_results = [r for r in results if "broken" in str(r["name"])]
        assert len(broken_results) == 1
        assert broken_results[0]["ok"] is False
        assert broken_results[0]["severity"] == "warning"

    def test_skill_import_error(self, tmp_path: Path, monkeypatch) -> None:
        """skill entry_point 导入失败时报告 warning。"""
        broken_skills_dir = tmp_path / "broken_skills"
        broken_skills_dir.mkdir()
        broken_stage = broken_skills_dir / "broken"
        broken_stage.mkdir()
        (broken_stage / "__init__.py").write_text('"""broken"""\n', encoding="utf-8")
        sr = SkillRegistry(broken_skills_dir)

        from importlib.util import find_spec as real_find_spec

        def fake_find_spec(name, *args, **kwargs):
            if "broken" in name:
                raise ImportError(f"Cannot import {name}")
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr("news_sentry.core.adapter_health.find_spec", fake_find_spec)

        results = check_all_adapters(sr)
        skill_results = [r for r in results if "broken" in str(r["name"])]
        assert len(skill_results) == 1
        assert skill_results[0]["ok"] is False
        assert skill_results[0]["severity"] == "warning"

    def test_empty_registry(self, tmp_path: Path) -> None:
        """空注册中心返回空结果列表。"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        sr = SkillRegistry(empty_dir)
        results = check_all_adapters(sr)
        assert results == []
