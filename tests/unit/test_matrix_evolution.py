"""Tests for MatrixEvolution — Phase 21 信源矩阵自进化."""

from __future__ import annotations

from pathlib import Path

import yaml

from news_sentry.core.matrix_evolution import CandidateSource, MatrixEvolution
from news_sentry.skills.collect.rss_discovery import DiscoveredFeed, DiscoveryResult


def _write_target_yaml(path: Path, source_refs: list[str] | None = None) -> Path:
    """辅助：写入 target YAML 配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "target_id": "italy",
        "source_channel_refs": source_refs or ["src1"],
    }
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


class TestCandidateSource:
    """CandidateSource 数据类测试。"""

    def test_construction(self) -> None:
        c = CandidateSource(
            url="https://example.com/new-feed",
            title="New Feed",
            feed_type="rss",
            discovered_from="src1",
        )
        assert c.status == "pending"
        assert c.reviewer_note == ""

    def test_to_dict(self) -> None:
        c = CandidateSource(url="https://example.com/feed", title="Test")
        d = c.to_dict()
        assert d["url"] == "https://example.com/feed"
        assert d["status"] == "pending"


class TestMatrixEvolution:
    """MatrixEvolution 核心逻辑测试。"""

    def test_ingest_discovery_adds_candidates(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://new.com/rss", title="New", feed_type="rss"),
            ],
        )
        added = evo.ingest_discovery(result)
        assert added == 1
        assert len(evo.get_pending()) == 1

    def test_ingest_skips_rejected(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        # 先注入再拒绝
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://bad.com/rss"),
            ],
        )
        evo.ingest_discovery(result)
        evo.reject("https://bad.com/rss", "spam")

        # 再次注入同样的 URL 应跳过
        result2 = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://bad.com/rss"),
            ],
        )
        added = evo.ingest_discovery(result2)
        assert added == 0

    def test_ingest_skips_existing(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://new.com/rss"),
            ],
        )
        evo.ingest_discovery(result)
        # 再次注入
        added = evo.ingest_discovery(result)
        assert added == 0

    def test_approve_generates_source_yaml(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(
                    url="https://new.com/feed.xml",
                    title="New Source",
                    feed_type="rss",
                ),
            ],
        )
        evo.ingest_discovery(result)

        source_path = evo.approve("https://new.com/feed.xml", "new-src", credibility_base=0.7)
        assert source_path is not None
        assert source_path.exists()
        with open(source_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["source_id"] == "new-src"
        assert data["url"] == "https://new.com/feed.xml"
        assert data["credibility_base"] == 0.7
        assert data["enabled"] is True

    def test_approve_adds_to_target_refs(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(
            tmp_path / "targets" / "italy.yaml",
            source_refs=["src1", "src2"],
        )
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://new.com/rss"),
            ],
        )
        evo.ingest_discovery(result)
        evo.approve("https://new.com/rss", "new-src")

        with open(target_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "new-src" in data["source_channel_refs"]

    def test_reject_marks_source(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://bad.com/rss"),
            ],
        )
        evo.ingest_discovery(result)
        ok = evo.reject("https://bad.com/rss", "spam")
        assert ok is True
        assert len(evo.get_pending()) == 0

    def test_approve_non_pending_returns_none(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = evo.approve("https://nonexistent.com/rss", "src")
        assert result is None

    def test_state_persistence(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(tmp_path / "targets" / "italy.yaml")
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        # 第一次写入
        evo1 = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[
                DiscoveredFeed(url="https://a.com/rss"),
                DiscoveredFeed(url="https://b.com/rss"),
            ],
        )
        evo1.ingest_discovery(result)
        evo1.reject("https://b.com/rss", "low quality")

        # 重新加载
        evo2 = MatrixEvolution(source_dir, target_path, state_path)
        assert len(evo2.get_pending()) == 1
        assert len(evo2.get_all_candidates()) == 2

    def test_no_duplicate_in_target_refs(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "sources"
        target_path = _write_target_yaml(
            tmp_path / "targets" / "italy.yaml",
            source_refs=["src1"],
        )
        state_path = tmp_path / "memory" / "matrix-evolution.yaml"

        evo = MatrixEvolution(source_dir, target_path, state_path)
        result = DiscoveryResult(
            target_id="italy",
            new_feeds=[DiscoveredFeed(url="https://new.com/rss")],
        )
        evo.ingest_discovery(result)
        evo.approve("https://new.com/rss", "src1")  # same ref

        with open(target_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # src1 不应重复
        assert data["source_channel_refs"].count("src1") == 1
