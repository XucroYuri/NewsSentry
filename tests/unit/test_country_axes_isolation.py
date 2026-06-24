"""country_axes 隔离验证测试 — Phase 7 确保 target 独占轴不泄漏到其他 target。"""

from __future__ import annotations

import pytest

from news_sentry.core.config import (
    ITALY_SPECIFIC_AXES,
    TARGET_SPECIFIC_AXES,
    validate_country_axes_isolation,
)


class TestCountryAxesIsolation:
    def test_italy_target_allows_all_axes(self):
        """意大利目标允许使用所有专有轴（通过 config/targets/italy.yaml 声明）。"""
        classification = {
            "country_axes": {
                "coalition": "centrodestra",
                "eu_role": "eu-parliament",
                "region": "Lazio",
                "china_italy_relations": "trade",
            },
        }
        validate_country_axes_isolation("italy", classification)  # 不应抛异常

    def test_non_italy_target_with_coalition_raises(self):
        """其他 target 含 coalition 轴应抛 ValueError（为意大利独占轴）。"""
        classification = {"country_axes": {"coalition": "centrodestra"}}
        with pytest.raises(ValueError, match="coalition"):
            validate_country_axes_isolation("japan", classification)

    def test_non_italy_target_with_eu_role_raises(self):
        """其他 target 含 eu_role 轴应抛 ValueError。"""
        classification = {"country_axes": {"eu_role": "eu-commissioner"}}
        with pytest.raises(ValueError, match="eu_role"):
            validate_country_axes_isolation("france", classification)

    def test_non_italy_target_with_region_raises(self):
        """其他 target 含 region 轴应抛 ValueError。"""
        classification = {"country_axes": {"region": "Lazio"}}
        with pytest.raises(ValueError, match="region"):
            validate_country_axes_isolation("germany", classification)

    def test_non_italy_target_with_china_italy_relations_raises(self):
        """其他 target 含 china_italy_relations 轴应抛 ValueError。"""
        classification = {"country_axes": {"china_italy_relations": "trade"}}
        with pytest.raises(ValueError, match="china_italy_relations"):
            validate_country_axes_isolation("japan", classification)

    def test_non_italy_target_with_clean_axes_passes(self):
        """其他 target 使用合法轴应通过。"""
        classification = {"country_axes": {"politics": True, "economics": True}}
        validate_country_axes_isolation("japan", classification)  # 不应抛异常

    def test_empty_country_axes_passes(self):
        """空的 country_axes 应通过。"""
        validate_country_axes_isolation("japan", {"country_axes": {}})
        validate_country_axes_isolation("japan", {})

    def test_target_specific_axes_constant(self):
        """TARGET_SPECIFIC_AXES 常量包含预期轴名（向后兼容）。"""
        assert "coalition" in TARGET_SPECIFIC_AXES
        assert "eu_role" in TARGET_SPECIFIC_AXES
        assert "region" in TARGET_SPECIFIC_AXES
        assert "china_italy_relations" in TARGET_SPECIFIC_AXES

    def test_italy_specific_axes_backward_compat(self):
        """ITALY_SPECIFIC_AXES 仍然可用（向后兼容）。"""
        assert ITALY_SPECIFIC_AXES == TARGET_SPECIFIC_AXES

    def test_target_without_config_still_checked(self):
        """没有配置文件的 target 仍会被检查（防御性：不因缺少配置而放行）。"""
        classification = {
            "country_axes": {
                "coalition": "centrodestra",
                "eu_role": "eu-parliament",
            },
        }
        # "nonexistent-target" 没有 target YAML，但 italy 声明了 coalition/eu_role 为独占轴
        # 因此 nonexistent-target 使用这些轴仍应被拒绝
        # frozenset 转 set 的迭代顺序在不同 hash seed 下可能不同，匹配任一轴即可
        with pytest.raises(ValueError, match="coalition|eu_role"):
            validate_country_axes_isolation("nonexistent-target", classification)
