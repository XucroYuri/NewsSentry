"""country_axes 隔离验证测试 — Phase 7 确保意大利专有轴不泄漏到其他国家。"""

from __future__ import annotations

import pytest

from news_sentry.core.config import (
    ITALY_SPECIFIC_AXES,
    validate_country_axes_isolation,
)


class TestCountryAxesIsolation:
    def test_italy_target_allows_all_axes(self):
        """意大利目标允许使用所有专有轴。"""
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
        """非意大利目标含 coalition 轴应抛 ValueError。"""
        classification = {"country_axes": {"coalition": "centrodestra"}}
        with pytest.raises(ValueError, match="coalition"):
            validate_country_axes_isolation("japan", classification)

    def test_non_italy_target_with_eu_role_raises(self):
        """非意大利目标含 eu_role 轴应抛 ValueError。"""
        classification = {"country_axes": {"eu_role": "eu-commissioner"}}
        with pytest.raises(ValueError, match="eu_role"):
            validate_country_axes_isolation("france", classification)

    def test_non_italy_target_with_region_raises(self):
        """非意大利目标含 region 轴应抛 ValueError。"""
        classification = {"country_axes": {"region": "Lazio"}}
        with pytest.raises(ValueError, match="region"):
            validate_country_axes_isolation("germany", classification)

    def test_non_italy_target_with_china_italy_relations_raises(self):
        """非意大利目标含 china_italy_relations 轴应抛 ValueError。"""
        classification = {"country_axes": {"china_italy_relations": "trade"}}
        with pytest.raises(ValueError, match="china_italy_relations"):
            validate_country_axes_isolation("japan", classification)

    def test_non_italy_target_with_clean_axes_passes(self):
        """非意大利目标使用合法轴应通过。"""
        classification = {"country_axes": {"politics": True, "economics": True}}
        validate_country_axes_isolation("japan", classification)  # 不应抛异常

    def test_empty_country_axes_passes(self):
        """空的 country_axes 应通过。"""
        validate_country_axes_isolation("japan", {"country_axes": {}})
        validate_country_axes_isolation("japan", {})

    def test_italy_specific_axes_constant(self):
        """ITALY_SPECIFIC_AXES 常量包含预期轴名。"""
        assert "coalition" in ITALY_SPECIFIC_AXES
        assert "eu_role" in ITALY_SPECIFIC_AXES
        assert "region" in ITALY_SPECIFIC_AXES
        assert "china_italy_relations" in ITALY_SPECIFIC_AXES
