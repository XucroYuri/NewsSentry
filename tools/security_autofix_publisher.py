#!/usr/bin/env python3
"""Turn deployment surface audit findings into a publish/no-publish plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from deployment_surface_security import load_policy, plan_autofix_publish


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan low-risk deployment surface autofix publishing."
    )
    parser.add_argument("--policy", required=True, help="Path to deployment surface policy YAML.")
    parser.add_argument(
        "--audit-json",
        required=True,
        help="JSON report created by deployed_surface_audit.py.",
    )
    parser.add_argument("--output", required=True, help="Where to write the JSON publish plan.")
    args = parser.parse_args()

    policy = load_policy(args.policy)
    audit_report = _load_json(Path(args.audit_json))
    publish_plan = plan_autofix_publish(audit_report, policy)
    _write_json(Path(args.output), publish_plan)
    print(
        json.dumps(
            {
                "should_publish": publish_plan["should_publish"],
                "fixable_count": publish_plan["summary"]["fixable_count"],
                "blocker_count": publish_plan["summary"]["blocker_count"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if publish_plan["stop_reasons"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
