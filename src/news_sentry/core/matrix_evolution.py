"""Implements: docs/spec/phase-21-rss-auto-discovery.md §3

MatrixEvolution — 信源矩阵自进化引擎。

工作流程:
  1. 接收 RSSDiscovery 的 DiscoveryResult
  2. 新源进入候选队列（pending_approval）
  3. 人工审批后（approve/reject）自动生成 source YAML 配置
  4. 审批通过的源纳入矩阵，添加到 target.yaml 的 source_channel_refs
  5. 审批拒绝的源记入拒绝列表，避免重复发现

持久化: data/{target_id}/memory/matrix-evolution.yaml
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from news_sentry.skills.collect.rss_discovery import DiscoveryResult


class CandidateSource:
    """候选信源（待审批）。"""

    __slots__ = (
        "url",
        "title",
        "feed_type",
        "discovered_from",
        "status",
        "discovered_at",
        "reviewed_at",
        "reviewer_note",
    )

    def __init__(
        self,
        url: str,
        title: str = "",
        feed_type: str = "rss",
        discovered_from: str = "",
        status: str = "pending",
        discovered_at: str = "",
        reviewed_at: str = "",
        reviewer_note: str = "",
    ) -> None:
        self.url = url
        self.title = title
        self.feed_type = feed_type
        self.discovered_from = discovered_from
        self.status = status  # pending | approved | rejected
        self.discovered_at = discovered_at
        self.reviewed_at = reviewed_at
        self.reviewer_note = reviewer_note

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "feed_type": self.feed_type,
            "discovered_from": self.discovered_from,
            "status": self.status,
            "discovered_at": self.discovered_at,
            "reviewed_at": self.reviewed_at,
            "reviewer_note": self.reviewer_note,
        }


class MatrixEvolution:
    """信源矩阵自进化引擎。

    管理候选源队列，审批后自动生成配置并纳入矩阵。
    """

    def __init__(
        self,
        source_dir: Path,
        target_config_path: Path,
        state_path: Path,
        audit_log_path: Path | None = None,
        rss_discovery_cooldown_hours: int = 168,
    ) -> None:
        """初始化 MatrixEvolution。

        Args:
            source_dir: 信源配置目录（如 config/sources/my-target/）。
            target_config_path: target 配置文件路径（如 config/targets/my-target.yaml）。
            state_path: 进化状态持久化路径（如 data/my-target/memory/matrix-evolution.yaml）。
            audit_log_path: 审计日志路径（JSONL）。None 时不记日志。
            rss_discovery_cooldown_hours: RSS 发现冷却时间（默认 168h=7d）。
        """
        self._source_dir = source_dir
        self._target_config_path = target_config_path
        self._state_path = state_path
        self._audit_log_path = audit_log_path
        self._cooldown_hours = rss_discovery_cooldown_hours
        self._candidates: dict[str, CandidateSource] = {}
        self._rejected_urls: set[str] = set()
        self._last_discovery_at: str = ""
        self._load_state()

    def ingest_discovery(self, result: DiscoveryResult) -> int:
        """将发现结果注入候选队列。

        过滤已审批、已拒绝的源，仅保留新候选。
        遵守 rss_discovery_cooldown_hours 冷却期。

        Returns:
            新增候选数量。
        """
        # 检查冷却期
        if self._last_discovery_at:
            try:
                last = datetime.fromisoformat(self._last_discovery_at)
                elapsed = (datetime.now(UTC) - last).total_seconds() / 3600
                if elapsed < self._cooldown_hours:
                    return 0
            except (ValueError, TypeError):
                pass

        added = 0
        now = datetime.now(UTC).isoformat()
        for feed in result.new_feeds:
            if feed.url in self._rejected_urls:
                continue
            if feed.url in self._candidates:
                continue
            self._candidates[feed.url] = CandidateSource(
                url=feed.url,
                title=feed.title,
                feed_type=feed.feed_type,
                discovered_from=feed.discovered_from,
                status="pending",
                discovered_at=now,
            )
            added += 1
        if added > 0:
            self._last_discovery_at = now
            self._save_state()
        return added

    def approve(self, url: str, source_id: str, credibility_base: float = 0.5) -> Path | None:
        """审批通过候选源，自动生成 source YAML 并纳入 target 配置。

        Args:
            url: 候选源 URL。
            source_id: 分配的 source_id。
            credibility_base: 基础可信度。

        Returns:
            生成的 source YAML 文件路径，或 None（URL 不在候选中）。
        """
        candidate = self._candidates.get(url)
        if candidate is None or candidate.status != "pending":
            return None

        now = datetime.now(UTC).isoformat()
        candidate.status = "approved"
        candidate.reviewed_at = now

        # 审计日志
        self._write_audit(
            "approve",
            url,
            {
                "source_id": source_id,
                "credibility_base": credibility_base,
            },
        )

        # 生成 source YAML
        source_path = self._generate_source_yaml(source_id, candidate, credibility_base)

        # 添加到 target.yaml 的 source_channel_refs
        self._add_to_target_refs(source_id)

        self._save_state()
        return source_path

    def reject(self, url: str, note: str = "") -> bool:
        """审批拒绝候选源。

        Args:
            url: 候选源 URL。
            note: 拒绝原因。

        Returns:
            是否成功拒绝。
        """
        candidate = self._candidates.get(url)
        if candidate is None or candidate.status != "pending":
            return False

        now = datetime.now(UTC).isoformat()
        candidate.status = "rejected"
        candidate.reviewed_at = now
        candidate.reviewer_note = note
        self._rejected_urls.add(url)

        # 审计日志
        self._write_audit("reject", url, {"note": note})

        self._save_state()
        return True

    def get_pending(self) -> list[CandidateSource]:
        """返回所有待审批的候选源。"""
        return [c for c in self._candidates.values() if c.status == "pending"]

    def get_all_candidates(self) -> list[CandidateSource]:
        """返回所有候选源。"""
        return list(self._candidates.values())

    def _generate_source_yaml(
        self,
        source_id: str,
        candidate: CandidateSource,
        credibility_base: float,
    ) -> Path:
        """生成 source YAML 配置文件。"""
        self._source_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "source_id": source_id,
            "display_name": candidate.title or source_id,
            "type": candidate.feed_type,
            "url": candidate.url,
            "credibility_base": credibility_base,
            "fetch_interval_minutes": 30,
            "max_items_per_run": 50,
            "timeout_seconds": 30,
            "enabled": True,
            "health": {
                "last_success_at": None,
                "consecutive_failures": 0,
            },
        }
        filepath = self._source_dir / f"{source_id}.yaml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return filepath

    def _add_to_target_refs(self, source_id: str) -> None:
        """将 source_id 添加到 target.yaml 的 source_channel_refs。"""
        if not self._target_config_path.is_file():
            return
        with open(self._target_config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return

        refs = data.get("source_channel_refs", [])
        if not isinstance(refs, list):
            refs = []
        if source_id not in refs:
            refs.append(source_id)
            data["source_channel_refs"] = refs
            with open(self._target_config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ── 持久化 ─────────────────────────────────────

    def _write_audit(self, action: str, url: str, detail: dict[str, Any]) -> None:
        """写一条 JSONL 审计日志。"""
        if self._audit_log_path is None:
            return
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "action": action,
            "url": url,
            "detail": detail,
        }
        with open(self._audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_state(self) -> None:
        """加载进化状态。"""
        if not self._state_path.is_file():
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            return

        if not isinstance(data, dict):
            return

        for item in data.get("candidates", []):
            if not isinstance(item, dict):
                continue
            url = item.get("url", "")
            if not url:
                continue
            self._candidates[url] = CandidateSource(
                url=url,
                title=str(item.get("title", "")),
                feed_type=str(item.get("feed_type", "rss")),
                discovered_from=str(item.get("discovered_from", "")),
                status=str(item.get("status", "pending")),
                discovered_at=str(item.get("discovered_at", "")),
                reviewed_at=str(item.get("reviewed_at", "")),
                reviewer_note=str(item.get("reviewer_note", "")),
            )

        for url in data.get("rejected_urls", []):
            self._rejected_urls.add(str(url))

        self._last_discovery_at = str(data.get("last_discovery_at", ""))

    def _save_state(self) -> None:
        """保存进化状态。"""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "candidates": [c.to_dict() for c in self._candidates.values()],
            "rejected_urls": sorted(self._rejected_urls),
            "updated_at": datetime.now(UTC).isoformat(),
            "last_discovery_at": self._last_discovery_at,
        }
        tmp_path = self._state_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        tmp_path.rename(self._state_path)
