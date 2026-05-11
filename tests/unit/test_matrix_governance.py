"""MatrixGovernance 模块测试。"""
import pytest
from news_sentry.core.matrix_governance import SourceLifecycle, SourceHealth


class TestSourceLifecycle:
    def test_active_to_degraded(self):
        """active 连续失败 3 次 → degraded。"""
        health = SourceHealth(source_id="test", degraded_after=3, dead_after=10)
        for _ in range(3):
            health.record_failure()
        assert health.state == SourceLifecycle.DEGRADED

    def test_degraded_to_active_on_success(self):
        """degraded 后成功 → active。"""
        health = SourceHealth(source_id="test", degraded_after=3, dead_after=10)
        for _ in range(3):
            health.record_failure()
        assert health.state == SourceLifecycle.DEGRADED
        health.record_success()
        assert health.state == SourceLifecycle.ACTIVE

    def test_degraded_to_dead(self):
        """degraded 连续失败到 10 次 → dead。"""
        health = SourceHealth(source_id="test", degraded_after=3, dead_after=10)
        for _ in range(10):
            health.record_failure()
        assert health.state == SourceLifecycle.DEAD


class TestHealthAudit:
    def test_get_degraded_sources(self):
        """审计返回所有 degraded 源。"""
        from news_sentry.core.matrix_governance import MatrixGovernance
        gov = MatrixGovernance()
        h1 = gov.get_or_create_health("src_a")
        for _ in range(3):
            h1.record_failure()
        degraded = gov.get_degraded_sources()
        assert "src_a" in degraded
