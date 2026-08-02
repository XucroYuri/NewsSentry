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
    assert triggers["workflow_dispatch"]["inputs"]["bootstrap_continuity"]["default"] == "false"
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
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
    previous = steps["Download previous continuity ledger"]["run"]
    continuity = steps["Update continuity ledger"]["run"]

    assert 'environment="production"' in resolve
    assert 'public_base_url="https://news-sentry.com"' in resolve
    assert 'api_base_url="https://api.news-sentry.com"' in resolve
    assert 'probe_api_base_url="https://news-sentry.com"' in resolve
    assert 'api_base_url="${INPUT_API_BASE_URL:-https://api.news-sentry.com}"' in resolve
    assert 'probe_api_base_url="${INPUT_PROBE_API_BASE_URL:-https://news-sentry.com}"' in resolve
    assert (
        'api_base_url="${INPUT_API_BASE_URL:-https://news-sentry-api-preview.xuyu.workers.dev}"'
        in resolve
    )
    assert 'probe_api_base_url="${INPUT_PROBE_API_BASE_URL:-${api_base_url}}"' in resolve
    assert 'printf \'%s=%s\\n\' "probe_api_base_url" "${probe_api_base_url}"' in resolve
    assert "Resolve deployed commit from guard receipt and deployment metadata" in resolve
    assert 'f"{api_base_url}/api/v1/live"' in resolve
    assert 'f"{api_base_url}/api/v1/ready"' not in resolve
    assert 'payload.get("status") != "ok"' in resolve
    assert "Deployment metadata live status is not ok." in resolve
    assert "re.fullmatch(r\"[0-9a-fA-F]{40}\"" in resolve
    assert 'expected_commit="${DEPLOYED_COMMIT}"' in resolve
    assert 'expected_commit="${GITHUB_SHA}"' not in resolve
    assert 'deployed_at="$(date -u' not in resolve
    assert "Production expected_commit is required" not in resolve
    assert 'Preview public_base_url is required.' in resolve
    assert "Deployment metadata expected_commit mismatch." in resolve
    assert "reject_multiline" in resolve
    assert "Invalid expected_commit: expected a 40-character Git commit SHA." in resolve
    assert "printf '%s=%s\\n'" in resolve
    assert "cloudflare-continuity-ledger-" in previous
    assert "--status success" in previous
    assert "for previous_run_id in" in previous
    assert 'prefix="cloudflare-continuity-ledger-${ENVIRONMENT}-${EXPECTED_COMMIT}-"' in previous
    assert '--arg prefix "${prefix}"' in previous
    assert (
        'startswith("cloudflare-continuity-ledger-${ENVIRONMENT}-${EXPECTED_COMMIT}-")'
        not in previous
    )
    assert "bootstrap_continuity" in previous
    assert "No previous continuity ledger found" in previous
    assert "Ledger deployed_commit does not match expected commit" in previous
    assert "/tmp/news-sentry-cloudflare-continuity-ledger.jsonl" in previous  # noqa: S108
    assert "tools/cloudflare_continuity_ledger.py append" in continuity
    assert "--source-health-current /tmp/news-sentry-source-health-slo.json" in continuity
    assert "--source-health-start /tmp/news-sentry-source-health-slo-start.json" in continuity
    assert "--source-health-end /tmp/news-sentry-source-health-slo-end.json" in continuity
    probe = steps["Probe split Cloudflare runtime"]["run"]
    probe_env = steps["Probe split Cloudflare runtime"]["env"]
    assert probe_env["API_BASE_URL"] == "${{ steps.target.outputs.api_base_url }}"
    assert probe_env["PROBE_API_BASE_URL"] == "${{ steps.target.outputs.probe_api_base_url }}"
    assert '--api-base-url "${API_BASE_URL}"' in probe
    assert '--probe-api-base-url "${PROBE_API_BASE_URL}"' in probe

    continuity_artifact = steps["Upload continuity ledger receipt"]
    expected_artifact_name = (
        "cloudflare-continuity-ledger-"
        "${{ steps.target.outputs.environment }}-"
        "${{ steps.target.outputs.expected_commit }}-"
        "${{ github.run_id }}"
    )
    assert (
        continuity_artifact["with"]["name"]
        == expected_artifact_name
    )
