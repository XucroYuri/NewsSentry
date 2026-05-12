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

    def test_load_invalid_yaml_returns_empty(self):
        """load() 对非法 YAML 应返回空 MatrixGovernance。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "invalid.yaml"
            filepath.write_text("{bad yaml: [unclosed", encoding="utf-8")
            gov = MatrixGovernance.load(filepath)
            assert gov.audit_summary()["total"] == 0

    def test_load_non_dict_data_returns_empty(self):
        """load() 对 YAML 解析为列表的数据应返回空 MatrixGovernance。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "list.yaml"
            import yaml

            filepath.write_text(yaml.dump(["item1", "item2"]), encoding="utf-8")
            gov = MatrixGovernance.load(filepath)
            assert gov.audit_summary()["total"] == 0

    def test_load_skips_non_dict_source_entry(self):
        """load() 应跳过 sources 列表中非 dict 类型的条目。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "mixed.yaml"
            import yaml

            data = {
                "sources": [
                    "not_a_dict",
                    {
                        "source_id": "valid_src",
                        "state": "ACTIVE",
                        "consecutive_failures": 0,
                        "consecutive_successes": 5,
                    },
                    123,
                ],
            }
            filepath.write_text(yaml.dump(data), encoding="utf-8")
            gov = MatrixGovernance.load(filepath)
            assert gov.audit_summary()["total"] == 1
            assert "valid_src" in gov._health

    def test_load_skips_source_without_id(self):
        """load() 应跳过 sources 中缺少 source_id 的条目。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "no_id.yaml"
            import yaml

            data = {
                "sources": [
                    {"state": "ACTIVE", "consecutive_failures": 0, "consecutive_successes": 3},
                    {
                        "source_id": "has_id",
                        "state": "DEGRADED",
                        "consecutive_failures": 4,
                        "consecutive_successes": 0,
                    },
                ],
            }
            filepath.write_text(yaml.dump(data), encoding="utf-8")
            gov = MatrixGovernance.load(filepath)
            assert gov.audit_summary()["total"] == 1
            assert "has_id" in gov._health

    def test_load_unknown_state_defaults_to_active(self):
        """load() 对未知 state 名称应回退为 ACTIVE。"""
        with tempfile.TemporaryDirectory() as td:
            filepath = Path(td) / "unknown_state.yaml"
            import yaml

            data = {
                "sources": [
                    {
                        "source_id": "src_x",
                        "state": "NONEXISTENT_STATE",
                        "consecutive_failures": 7,
                        "consecutive_successes": 0,
                    },
                ],
            }
            filepath.write_text(yaml.dump(data), encoding="utf-8")
            gov = MatrixGovernance.load(filepath)
            assert gov._health["src_x"].state == SourceLifecycle.ACTIVE
            assert gov._health["src_x"].consecutive_failures == 7
