"""Phase 4: Adapter health check — pre-run validation of skills."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from news_sentry.core.skill_registry import SkillRegistry


def check_all_adapters(
    skill_registry: SkillRegistry,
) -> list[dict[str, Any]]:
    """执行所有 adapter 健康检查，返回结构化结果列表。

    每条结果: {name, ok, severity, message}
    - Skills: 检查 entry_point 是否可导入
    """
    results: list[dict[str, Any]] = []

    # ── Skills 健康检查 ──────────────────────────────────────
    for skill in skill_registry.list_skills():
        ep = skill.entry_point
        try:
            spec = find_spec(ep)
            if spec is None:
                results.append(
                    {
                        "name": f"Skill: {skill.skill_id}",
                        "ok": False,
                        "severity": "warning",
                        "message": f"entry_point not found: {ep}",
                    }
                )
            else:
                results.append(
                    {
                        "name": f"Skill: {skill.skill_id}",
                        "ok": True,
                        "severity": "info",
                        "message": ep,
                    }
                )
        except (ImportError, ModuleNotFoundError, ValueError) as e:
            results.append(
                {
                    "name": f"Skill: {skill.skill_id}",
                    "ok": False,
                    "severity": "warning",
                    "message": f"{ep}: {e}",
                }
            )

    return results
