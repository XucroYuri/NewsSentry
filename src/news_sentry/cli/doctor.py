"""News Sentry — CLI doctor: 项目健康检查."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

REQUIRED_DIRS = [
    "raw",
    "evaluated",
    "drafts",
    "reviewed",
    "published",
    "archive",
    "memory",
    "logs",
]

_AI_KEY_VARS = ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY")


class DoctorReport(BaseModel):
    schema_check: dict[str, Any] = {}
    directory_check: dict[str, Any] = {}
    source_check: dict[str, Any] = {}
    provider_check: dict[str, Any] = {}
    browser_bridge_check: dict[str, Any] = {}
    session_profiles_check: dict[str, Any] = {}
    glossary_check: dict[str, Any] = {}

    @property
    def all_passed(self) -> bool:
        checks = [
            self.schema_check,
            self.directory_check,
            self.source_check,
            self.provider_check,
            self.browser_bridge_check,
            self.session_profiles_check,
            self.glossary_check,
        ]
        return all(c.get("passed", False) for c in checks if c)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_check": self.schema_check,
            "directory_check": self.directory_check,
            "source_check": self.source_check,
            "provider_check": self.provider_check,
            "browser_bridge_check": self.browser_bridge_check,
            "session_profiles_check": self.session_profiles_check,
            "glossary_check": self.glossary_check,
            "overall": "PASS" if self.all_passed else "FAIL",
        }


def run_doctor(target_id: str, data_root: str = "data") -> DoctorReport:
    data_path = Path(data_root) / target_id

    # Schema check
    schema_ok = True
    schema_details: list[str] = []
    schemas_dir = Path("schemas")
    if schemas_dir.is_dir():
        schema_count = len(list(schemas_dir.glob("*.json")))
        schema_details.append(f"{schema_count} schema files found")
    else:
        schema_ok = False
        schema_details.append("schemas/ directory missing")

    # Directory check
    dir_ok = True
    dir_details: list[str] = []
    for d in REQUIRED_DIRS:
        p = data_path / d
        if p.is_dir():
            dir_details.append(f"{d}/ exists")
        else:
            dir_ok = False
            dir_details.append(f"{d}/ MISSING")

    # Source check — placeholder (network required)
    source_ok = True
    source_details = ["source reachability check requires network (skip in CI)"]

    # Provider check
    provider_ok = any(os.environ.get(var) for var in _AI_KEY_VARS)
    provider_details: list[str] = []
    for var in _AI_KEY_VARS:
        if os.environ.get(var):
            provider_details.append(f"{var} is set")
        else:
            provider_details.append(f"{var} not set")
    if not provider_ok:
        provider_details.append(
            "set GEMINI_API_KEY, DEEPSEEK_API_KEY, or GROQ_API_KEY for AI enrichment"
        )

    # Browser Bridge（v2 已移除，社媒采集由 RSS-Bridge 替代）
    bridge_ok = True
    bridge_details: list[str] = ["browser features removed in v2 (use rss-bridge for social media)"]

    # Session Profiles check
    session_ok = True
    session_details: list[str] = []
    session_dir = Path(f"config/session-profiles/{target_id}")
    if not session_dir.exists():
        session_ok = False
        session_details.append(f"config/session-profiles/{target_id}/ not found")
    else:
        yaml_files = list(session_dir.glob("*.yaml"))
        session_files = list(session_dir.glob("*.session.*"))
        session_details.append(
            f"{len(yaml_files)} session configs, {len(session_files)} session files"
        )

    # Glossary coverage check — 从 target 配置中读取 glossary_ref，
    # 若无配置则跳过（仅部分 target 有术语表）
    glossary_ok = True
    glossary_details: list[str] = []
    glossary_path = _resolve_glossary_path(target_id)
    if glossary_path is None:
        glossary_ok = True  # 无术语表不是错误，跳过
        glossary_details.append("no glossary configured for this target (skip)")
    elif not glossary_path.is_file():
        glossary_ok = False
        glossary_details.append(f"{glossary_path} not found")
    else:
        glossary_terms = _extract_glossary_terms(glossary_path)
        glossary_details.append(f"{len(glossary_terms)} glossary terms")
        eval_files = sorted(Path("data/eval").glob("eval-set-v*.json"))
        if eval_files:
            latest_eval = eval_files[-1]
            total, covered = _count_eval_coverage(latest_eval, glossary_terms)
            pct = covered / total * 100 if total > 0 else 0
            glossary_details.append(f"eval coverage: {covered}/{total} ({pct:.0f}%)")
            if pct < 50:
                glossary_ok = False
                glossary_details.append("coverage below 50% threshold")
        else:
            glossary_details.append("no eval-set files found (skip coverage check)")

    return DoctorReport(
        schema_check={"passed": schema_ok, "details": schema_details},
        directory_check={"passed": dir_ok, "details": dir_details},
        source_check={"passed": source_ok, "details": source_details},
        provider_check={"passed": provider_ok, "details": provider_details},
        browser_bridge_check={"passed": bridge_ok, "details": bridge_details},
        session_profiles_check={"passed": session_ok, "details": session_details},
        glossary_check={"passed": glossary_ok, "details": glossary_details},
    )


def doctor_command(target: str, data_root: str = "data", json_output: bool = False) -> int:
    report = run_doctor(target, data_root)
    if json_output:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report.all_passed else "FAIL"
        print(f"Doctor check: {status}")
        for check_name, check in report.to_dict().items():
            if check_name == "overall":
                continue
            icon = "PASS" if check.get("passed") else "FAIL"
            print(f"  [{icon}] {check_name}")
            for detail in check.get("details", []):
                print(f"     {detail}")
    return 0 if report.all_passed else 1


def _resolve_glossary_path(target_id: str) -> Path | None:
    """从 target 配置中解析术语表路径。

    检查 config/targets/{target_id}.yaml 中的 glossary_ref 字段，
    若无配置则返回 None（仅部分 target 有术语表）。
    """
    import yaml

    target_yaml = Path(f"config/targets/{target_id}.yaml")
    if not target_yaml.is_file():
        return None
    try:
        data = yaml.safe_load(target_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    ref = data.get("glossary_ref")
    if isinstance(ref, str) and ref:
        return Path(ref)
    return None


def _extract_glossary_terms(glossary_path: Path) -> set[str]:
    """从术语表 Markdown 中提取第一列词条（语言感知）。"""
    terms: set[str] = set()
    in_table = False
    for line in glossary_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and "意大利语" in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")]
            # 过滤分隔行和空行
            if len(cells) >= 2 and cells[1] and not cells[1].startswith("-"):
                term = cells[1]
                if term and term != "意大利语":
                    terms.add(term.lower())
        elif in_table and not stripped.startswith("|"):
            in_table = False
    return terms


def _count_eval_coverage(eval_path: Path, glossary_terms: set[str]) -> tuple[int, int]:
    """统计评估集中有多少条目的 input 涉及术语表词条。"""
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    examples = data.get("examples", [])
    total = len(examples)
    covered = 0
    for ex in examples:
        inp = ex.get("input", {})
        text = " ".join(
            [
                inp.get("title_original", ""),
                inp.get("content_original", ""),
                inp.get("title", ""),
                inp.get("content", ""),
                inp.get("source_id", ""),
            ]
        ).lower()
        if any(term in text for term in glossary_terms):
            covered += 1
    return total, covered
