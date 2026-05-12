"""MatrixGovernance 模块测试。"""

import tempfile
from pathlib import Path

from news_sentry.core.matrix_governance import (
    MatrixGovernance,
    SourceHealth,
    SourceLifecycle,
)


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
        gov = MatrixGovernance()
        h1 = gov.get_or_create_health("src_a")
        for _ in range(3):
            h1.record_failure()
        degraded = gov.get_degraded_sources()
        assert "src_a" in degraded


class TestPersistenceSave:
    """MatrixGovernance.save() — 将内存状态持久化到 YAML 文件。"""

    def test_save_creates_file(self):
        """save() 应在指定路径创建 YAML 文件。"""
        gov = MatrixGovernance()
        gov.get_or_create_health("src_a")
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "matrix-governance.yaml"
            gov.save(filepath)
            assert filepath.exists()

    def test_save_writes_valid_yaml(self):
        """save() 应写入合法 YAML，可被加载。"""
        import yaml

        gov = MatrixGovernance()
        gov.record_result("src_a", True)
        gov.record_result("src_b", False)
        gov.record_result("src_b", False)
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "matrix-governance.yaml"
            gov.save(filepath)
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert data is not None
            assert "sources" in data
            assert len(data["sources"]) == 2

    def test_save_includes_all_source_fields(self):
        """save() 应包含每个 source 的 source_id / state / failures / successes。"""
        gov = MatrixGovernance()
        gov.record_result("src_a", False)
        gov.record_result("src_b", True)
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "matrix-governance.yaml"
            gov.save(filepath)
            import yaml

            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            src_a = next(s for s in data["sources"] if s["source_id"] == "src_a")
            assert src_a["state"] in ("ACTIVE", "DEGRADED", "DEAD")
            assert isinstance(src_a["consecutive_failures"], int)
            assert isinstance(src_a["consecutive_successes"], int)


class TestPersistenceLoad:
    """MatrixGovernance.load() — 从 YAML 文件恢复治理状态。"""

    def test_load_restores_state(self):
        """load() 应完整恢复保存的 source health 状态。"""
        gov = MatrixGovernance()
        for _ in range(3):
            gov.record_result("src_a", False)
        gov.record_result("src_b", True)
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "matrix-governance.yaml"
            gov.save(filepath)
            restored = MatrixGovernance.load(filepath)
        assert "src_a" in restored._health
        assert restored._health["src_a"].state == SourceLifecycle.DEGRADED
        assert restored._health["src_a"].consecutive_failures == 3

    def test_load_roundtrip_preserves_audit(self):
        """save → load → audit_summary 应一致。"""
        gov = MatrixGovernance()
        for sid in ["a", "b", "c"]:
            gov.get_or_create_health(sid)
        for _ in range(5):
            gov.record_result("a", False)
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "matrix-governance.yaml"
            gov.save(filepath)
            restored = MatrixGovernance.load(filepath)
        assert restored.audit_summary() == gov.audit_summary()

    def test_load_nonexistent_file_returns_empty(self):
        """load() 对不存在的文件应返回空 MatrixGovernance。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "nonexistent.yaml"
            gov = MatrixGovernance.load(filepath)
            assert gov.audit_summary()["total"] == 0

    def test_load_empty_file_returns_empty(self):
        """load() 对空文件应返回空 MatrixGovernance。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "empty.yaml"
            filepath.write_text("", encoding="utf-8")
            gov = MatrixGovernance.load(filepath)
            assert gov.audit_summary()["total"] == 0
