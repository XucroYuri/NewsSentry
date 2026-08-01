from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/cloudflare-runtime-health.yml"


def test_runtime_health_workflow_schedules_low_cost_production_receipts() -> None:
    assert WORKFLOW.exists(), "Cloudflare runtime health workflow is missing"
    workflow = yaml.load(
        WORKFLOW.read_text(),
        Loader=yaml.BaseLoader,  # noqa: S506 - preserves GitHub's `on` key.
    )

    triggers = workflow["on"]
    assert triggers["schedule"] == [{"cron": "17 */6 * * *"}]
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    job = workflow["jobs"]["runtime-health"]
    assert job["timeout-minutes"] == "5"
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    probe = steps["Probe split Cloudflare runtime"]
    assert "python tools/cloudflare_runtime_probe.py" in probe["run"]
    assert '--expected-commit "${EXPECTED_COMMIT}"' in probe["run"]
    assert '--output /tmp/news-sentry-cloudflare-runtime-receipt.json' in probe["run"]

    artifact = steps["Upload runtime receipt"]
    assert artifact["if"] == "always()"
    assert artifact["with"]["if-no-files-found"] == "error"
    assert artifact["with"]["retention-days"] == "14"
    assert (
        artifact["with"]["path"]
        == "/tmp/news-sentry-cloudflare-runtime-receipt.json"  # noqa: S108
    )


def test_runtime_health_workflow_defaults_schedules_to_production_and_fails_closed() -> None:
    assert WORKFLOW.exists(), "Cloudflare runtime health workflow is missing"
    workflow = yaml.load(
        WORKFLOW.read_text(),
        Loader=yaml.BaseLoader,  # noqa: S506 - preserves GitHub's `on` key.
    )
    job = workflow["jobs"]["runtime-health"]
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    resolve = steps["Resolve probe target"]["run"]

    assert 'environment="production"' in resolve
    assert 'public_base_url="https://news-sentry.com"' in resolve
    assert 'api_base_url="https://api.news-sentry.com"' in resolve
    assert 'expected_commit="${GITHUB_SHA}"' in resolve
    assert 'Preview public_base_url is required.' in resolve
    assert 'Preview expected_commit is required.' in resolve
    assert "reject_multiline" in resolve
    assert "Invalid expected_commit: expected a 40-character Git commit SHA." in resolve
    assert "printf '%s=%s\\n'" in resolve
