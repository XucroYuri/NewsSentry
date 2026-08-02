from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/source-health.yml"


def test_source_health_workflow_requires_previous_summary_or_bootstrap() -> None:
    workflow = yaml.load(
        WORKFLOW.read_text(),
        Loader=yaml.BaseLoader,  # noqa: S506 - preserves GitHub's `on` key.
    )

    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["bootstrap_weekly_slo"]["default"] == "false"
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}

    steps = {
        step["name"]: step
        for step in workflow["jobs"]["source-health"]["steps"]
        if "name" in step
    }
    previous = steps["Download previous Source Health SLO"]["run"]
    audit = steps["Live source health audit"]["run"]

    assert "source-health-receipts" in previous
    assert "news-sentry-source-health-slo-previous.json" in previous
    assert "bootstrap_weekly_slo" in previous
    assert "No previous Source Health SLO receipt found" in previous
    assert "--previous-summary-json /tmp/news-sentry-source-health-slo-previous.json" in audit
    assert "--allow-weekly-bootstrap" in audit
