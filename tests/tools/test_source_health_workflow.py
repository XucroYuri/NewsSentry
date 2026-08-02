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
    resolve = steps["Resolve Source Health SLO metadata"]["run"]

    assert "Resolve deployed commit from the latest successful main production receipt" in resolve
    assert "api/v1/live" not in resolve
    assert "api/v1/ready" not in resolve
    assert "gh run list --workflow deploy.yml --branch main --status success" in resolve
    assert 'artifact_name="cloudflare-production-deploy-receipt-${head_sha}"' in resolve
    assert "tools/deploy_receipt_metadata.py" in resolve
    assert '--expected-commit "${head_sha}"' in resolve
    assert "No validated successful main production deploy receipt found." in resolve
    assert "source-health-receipts" in previous
    assert "--status success" in previous
    assert "--status completed" not in previous
    assert "news-sentry-source-health-slo-previous.json" in previous
    assert "bootstrap_weekly_slo" in previous
    assert "No previous Source Health SLO receipt found" in previous
    assert "--previous-summary-json /tmp/news-sentry-source-health-slo-previous.json" in audit
    assert "--allow-weekly-bootstrap" in audit
    assert '--slo-environment "${SLO_ENVIRONMENT}"' in audit
    assert '--slo-deployed-commit "${SLO_DEPLOYED_COMMIT}"' in audit
