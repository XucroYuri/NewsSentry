"""kol_state 模块测试 — KOLEntry + load_kol_state + update_kol_state"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from news_sentry.core.kol_state import KOLEntry, load_kol_state, update_kol_state

# ── helpers ────────────────────────────────────────────────────

def _make_valid_kol(**overrides) -> dict:
    data = {
        "kol_id": "twitter:test_user",
        "platform": "twitter",
        "display_name": "测试 KOL",
        "account_url": "https://twitter.com/test_user",
        "first_observed_at": "2026-05-01T08:00:00+00:00",
        "last_active_at": "2026-05-10T12:00:00+00:00",
        "follower_count_approx": 50000,
        "relevance_tags": ["politics", "italy"],
        "last_content_sample": "这是最近的一条推文内容。",
        "china_relevance_score": 60,
        "observation_enabled": True,
        "observation_channel": "kol-experiment",
    }
    data.update(overrides)
    return data


# ── KOLEntry ──────────────────────────────────────────────────

class TestKOLEntryValid:
    def test_valid_construction(self):
        """正常构造 KOLEntry 应成功。"""
        entry = KOLEntry(**_make_valid_kol())
        assert entry.kol_id == "twitter:test_user"
        assert entry.platform == "twitter"
        assert entry.display_name == "测试 KOL"
        assert entry.follower_count_approx == 50000
        assert entry.china_relevance_score == 60
        assert entry.observation_enabled is True

    def test_default_values(self):
        """默认字段应有正确默认值。"""
        minimal = {
            "kol_id": "twitter:minimal",
            "platform": "twitter",
            "display_name": "最小 KOL",
            "account_url": "https://twitter.com/minimal",
            "first_observed_at": "2026-05-01T08:00:00+00:00",
        }
        entry = KOLEntry(**minimal)
        assert entry.last_active_at is None
        assert entry.follower_count_approx is None
        assert entry.relevance_tags == []
        assert entry.last_content_sample is None
        assert entry.china_relevance_score is None
        assert entry.observation_enabled is True
        assert entry.observation_channel == "kol-experiment"

    def test_nullable_fields_accept_none(self):
        """允许为 None 的字段接受 None 值。"""
        entry = KOLEntry(**_make_valid_kol(
            last_active_at=None,
            follower_count_approx=None,
            last_content_sample=None,
            china_relevance_score=None,
        ))
        assert entry.last_active_at is None
        assert entry.follower_count_approx is None
        assert entry.last_content_sample is None
        assert entry.china_relevance_score is None


class TestKOLEntryContentSample:
    def test_content_sample_exceeds_200_chars_raises(self):
        """last_content_sample 超过 200 字符应抛出 ValidationError。"""
        long_text = "测" * 201
        with pytest.raises(ValidationError, match="last_content_sample"):
            KOLEntry(**_make_valid_kol(last_content_sample=long_text))

    def test_content_sample_exactly_200_chars_passes(self):
        """last_content_sample 恰好 200 字符应通过。"""
        exact_text = "A" * 200
        entry = KOLEntry(**_make_valid_kol(last_content_sample=exact_text))
        assert len(entry.last_content_sample) == 200

    def test_content_sample_none_passes(self):
        """last_content_sample 为 None 应通过。"""
        entry = KOLEntry(**_make_valid_kol(last_content_sample=None))
        assert entry.last_content_sample is None


class TestKOLEntryChinaRelevanceScore:
    def test_score_above_100_raises(self):
        """china_relevance_score > 100 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="china_relevance_score"):
            KOLEntry(**_make_valid_kol(china_relevance_score=101))

    def test_score_below_0_raises(self):
        """china_relevance_score < 0 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="china_relevance_score"):
            KOLEntry(**_make_valid_kol(china_relevance_score=-1))

    def test_score_at_100_passes(self):
        """china_relevance_score == 100 应通过。"""
        entry = KOLEntry(**_make_valid_kol(china_relevance_score=100))
        assert entry.china_relevance_score == 100

    def test_score_at_0_passes(self):
        """china_relevance_score == 0 应通过。"""
        entry = KOLEntry(**_make_valid_kol(china_relevance_score=0))
        assert entry.china_relevance_score == 0

    def test_score_none_passes(self):
        """china_relevance_score 为 None 应通过。"""
        entry = KOLEntry(**_make_valid_kol(china_relevance_score=None))
        assert entry.china_relevance_score is None


# ── load_kol_state ────────────────────────────────────────────

class TestLoadKolState:
    def test_loads_valid_yaml(self, tmp_path: Path):
        """从 tmp_path 加载有效的 kol-state.yaml。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()

        entries = [
            _make_valid_kol(kol_id="twitter:user1", display_name="用户1"),
            _make_valid_kol(kol_id="twitter:user2", display_name="用户2"),
        ]
        state = {"entries": entries, "updated_at": "2026-05-11T00:00:00+00:00"}
        (memory_root / "kol-state.yaml").write_text(
            yaml.dump(state, allow_unicode=True), encoding="utf-8"
        )

        result = load_kol_state(memory_root)
        assert len(result) == 2
        assert "twitter:user1" in result
        assert "twitter:user2" in result
        assert result["twitter:user1"].display_name == "用户1"

    def test_missing_file_returns_empty_dict(self, tmp_path: Path):
        """文件不存在时返回空字典。"""
        result = load_kol_state(tmp_path / "memory")
        assert result == {}

    def test_empty_yaml_returns_empty_dict(self, tmp_path: Path):
        """空 YAML 文件返回空字典。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()
        (memory_root / "kol-state.yaml").write_text("", encoding="utf-8")

        result = load_kol_state(memory_root)
        assert result == {}

    def test_invalid_entries_skipped(self, tmp_path: Path):
        """无效条目被跳过（记录警告日志）。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()

        entries = [
            _make_valid_kol(kol_id="twitter:valid", display_name="有效"),
            {"kol_id": "twitter:bad", "display_name": "坏条目"},  # 缺少必填字段
        ]
        state = {"entries": entries}
        (memory_root / "kol-state.yaml").write_text(
            yaml.dump(state, allow_unicode=True), encoding="utf-8"
        )

        result = load_kol_state(memory_root)
        assert len(result) == 1
        assert "twitter:valid" in result


# ── update_kol_state ──────────────────────────────────────────

class TestUpdateKolState:
    def test_new_entry_created(self, tmp_path: Path):
        """新增 KOL 条目。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()

        # 先初始化空状态文件
        state = {"entries": [], "updated_at": "2026-05-11T00:00:00+00:00"}
        (memory_root / "kol-state.yaml").write_text(
            yaml.dump(state, allow_unicode=True), encoding="utf-8"
        )

        update_kol_state("twitter:new_user", {
            "platform": "twitter",
            "display_name": "新用户",
            "account_url": "https://twitter.com/new_user",
            "first_observed_at": "2026-05-11T08:00:00+00:00",
            "china_relevance_score": 75,
        }, memory_root)

        result = load_kol_state(memory_root)
        assert len(result) == 1
        assert "twitter:new_user" in result
        assert result["twitter:new_user"].display_name == "新用户"
        assert result["twitter:new_user"].china_relevance_score == 75

    def test_existing_entry_updated(self, tmp_path: Path):
        """更新已有 KOL 条目。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()

        entries = [
            _make_valid_kol(
                kol_id="twitter:test", display_name="旧名称", china_relevance_score=50,
            )
        ]
        state = {"entries": entries, "updated_at": "2026-05-01T00:00:00+00:00"}
        (memory_root / "kol-state.yaml").write_text(
            yaml.dump(state, allow_unicode=True), encoding="utf-8"
        )

        update_kol_state(
            "twitter:test",
            {"display_name": "新名称", "china_relevance_score": 80},
            memory_root,
        )

        result = load_kol_state(memory_root)
        assert len(result) == 1
        assert result["twitter:test"].display_name == "新名称"
        assert result["twitter:test"].china_relevance_score == 80
        # 未更新的字段保持不变
        assert result["twitter:test"].platform == "twitter"

    def test_multiple_entries_updated_independently(self, tmp_path: Path):
        """更新一个条目不影响其他条目。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()

        entries = [
            _make_valid_kol(kol_id="twitter:user1", display_name="用户1"),
            _make_valid_kol(kol_id="twitter:user2", display_name="用户2"),
        ]
        state = {"entries": entries}
        (memory_root / "kol-state.yaml").write_text(
            yaml.dump(state, allow_unicode=True), encoding="utf-8"
        )

        update_kol_state("twitter:user1", {"display_name": "用户1改"}, memory_root)

        result = load_kol_state(memory_root)
        assert len(result) == 2
        assert result["twitter:user1"].display_name == "用户1改"
        assert result["twitter:user2"].display_name == "用户2"

    def test_creates_file_if_not_exists(self, tmp_path: Path):
        """kol-state.yaml 不存在时，应创建新文件。"""
        memory_root = tmp_path / "memory"
        memory_root.mkdir()

        update_kol_state("twitter:first", {
            "platform": "twitter",
            "display_name": "首个用户",
            "account_url": "https://twitter.com/first",
            "first_observed_at": "2026-05-11T08:00:00+00:00",
        }, memory_root)

        result = load_kol_state(memory_root)
        assert len(result) == 1
        assert "twitter:first" in result
