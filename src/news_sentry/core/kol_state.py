"""KOL 状态管理：跟踪已知 KOL 实体及其元数据。

存储：{target}/memory/kol-state.yaml
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


class KOLEntry(BaseModel):
    """KOL 实体记录（公开账号信息，不含私密数据）。

    存入 memory/kol-state.yaml。
    """

    kol_id: str  # 如 "twitter:giorgiaMeloni"
    platform: str  # "twitter" | "zhihu" | "weixin"
    display_name: str
    account_url: str  # 公开主页 URL
    first_observed_at: str  # ISO datetime
    last_active_at: str | None = None
    follower_count_approx: int | None = None  # 允许 None
    relevance_tags: list[str] = []  # 如 ["politics", "target-pm"]
    last_content_sample: str | None = None  # ≤ 200 字
    china_relevance_score: int | None = None  # 0–100
    observation_enabled: bool = True
    observation_channel: str = "kol-experiment"

    @field_validator("last_content_sample")
    @classmethod
    def check_content_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 200:
            raise ValueError(f"last_content_sample 不能超过 200 字，当前长度: {len(v)}")
        return v

    @field_validator("china_relevance_score")
    @classmethod
    def check_score_range(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 100):
            raise ValueError(f"china_relevance_score 必须在 0-100 之间，当前值: {v}")
        return v


def load_kol_state(memory_root: Path) -> dict[str, KOLEntry]:
    """从 memory/kol-state.yaml 加载所有 KOL 实体记录。

    Returns empty dict if file doesn't exist.
    """
    state_file = memory_root / "kol-state.yaml"
    if not state_file.exists():
        return {}

    with open(state_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries: dict[str, KOLEntry] = {}
    items = data.get("entries", []) if isinstance(data, dict) else []
    for item in items:
        try:
            entry = KOLEntry(**item)
            entries[entry.kol_id] = entry
        except Exception as e:
            logger.warning("跳过无效 KOL 条目: %s error=%s", item.get("kol_id", "?"), e)
    return entries


def update_kol_state(kol_id: str, update: dict[str, Any], memory_root: Path) -> None:
    """更新或新增 KOL 实体记录，原子写入。

    如果 kol_id 已存在，合并更新；否则新增条目。
    """
    state_file = memory_root / "kol-state.yaml"

    # 加载现有状态
    existing = load_kol_state(memory_root)

    if kol_id in existing:
        # 更新现有条目
        existing_data = existing[kol_id].model_dump()
        existing_data.update(update)
        entry = KOLEntry(**existing_data)
    else:
        # 新增条目
        entry = KOLEntry(kol_id=kol_id, **update)

    existing[kol_id] = entry

    # 原子写入：先写临时文件，再 rename
    entries_list = [e.model_dump() for e in existing.values()]
    data = {
        "entries": entries_list,
        "updated_at": datetime.now(UTC).isoformat(),
    }

    tmp_path = state_file.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
    tmp_path.rename(state_file)
