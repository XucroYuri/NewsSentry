from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "deploy.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.load(
            _workflow_text(),
            Loader=yaml.BaseLoader,  # noqa: S506 - preserves GitHub's `on` key.
        ),
    )


def _job(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], _workflow()["jobs"][name])


def _step(job_name: str, step_name: str) -> dict[str, Any]:
    steps = cast(list[dict[str, Any]], _job(job_name)["steps"])
    return next(step for step in steps if step.get("name") == step_name)


def _step_names(job_name: str) -> list[str]:
    return [
        str(step.get("name", step.get("uses", "")))
        for step in cast(list[dict[str, Any]], _job(job_name)["steps"])
    ]


def _shell_tokens(script: str, pattern: str) -> list[str]:
    return re.findall(pattern, script)


def _shell_token_pairs(script: str, pattern: str) -> list[tuple[str, str]]:
    return cast(list[tuple[str, str]], re.findall(pattern, script))


def _run_deployment_mode_script(
    tmp_path: Path,
    *,
    event_name: str,
    ref: str,
    sha: str,
    requested_environment: str,
    expected_commit: str,
) -> subprocess.CompletedProcess[str]:
    workflow = _workflow()
    steps = workflow["jobs"]["ci"]["steps"]
    step = next(
        candidate
        for candidate in steps
        if candidate.get("name") == "Resolve and validate deployment mode"
    )
    output_path = tmp_path / "github-output"
    return subprocess.run(  # noqa: S603 - executes repository-owned workflow script.
        ["/bin/bash", "-c", step["run"]],
        check=False,
        capture_output=True,
        text=True,
        env={
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_REF": ref,
            "GITHUB_SHA": sha,
            "GITHUB_OUTPUT": str(output_path),
            "REQUESTED_ENVIRONMENT": requested_environment,
            "EXPECTED_COMMIT": expected_commit,
            "PATH": "/usr/bin:/bin",
        },
    )


def test_preview_deploy_workflow_uses_cloudflare_native_surfaces() -> None:
    workflow = _workflow_text()

    assert "Deploy Cloudflare Worker" in workflow
    assert "Deploy Cloudflare Pages" in workflow
    assert "preview.news-sentry.com" in workflow
    assert "api.news-sentry.com" in workflow
    assert "VITE_API_BASE: https://api.news-sentry.com" in workflow


def test_preview_deploy_workflow_has_no_vps_or_systemd_blocks() -> None:
    workflow = _workflow_text()

    forbidden = [
        "cat > \"${DEPLOY_BASE}/${ENV}/.env\"",
        "cat > \"/etc/systemd/system/${SERVICE}.service\"",
        "appleboy/ssh-action",
        "BWH_SSH",
        "systemctl",
        "NEWSSENTRY_DEPLOYMENT_ENV=vps",
    ]
    for token in forbidden:
        assert token not in workflow


def test_deploy_workflow_uses_fail_closed_cloudflare_preflight_and_receipts() -> None:
    workflow = _workflow_text()

    assert "tools/cloudflare_deploy_guard.py preflight" in workflow
    assert "tools/cloudflare_deploy_guard.py receipt" in workflow
    assert "node_modules/.bin/wrangler versions list --json" in workflow
    assert "node_modules/.bin/wrangler deployments list --json" in workflow
    assert "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id" in workflow
    assert "tools/cloudflare_deploy_guard.py record-runtime-receipts" in workflow
    assert "node_modules/.bin/wrangler queues list --json" not in workflow
    assert "--var \"SCHEDULER_MODE:shadow\"" in workflow
    assert "--var \"WORKER_NATIVE_COLLECT_ENABLED:false\"" in workflow


def test_preview_verification_requires_preview_worker_runtime_proof() -> None:
    workflow = _workflow_text()
    preview_job = workflow.split("  verify-preview:", 1)[1].split(
        "  verify-production:", 1
    )[0]

    assert (
        "needs: [ci, deploy-cloudflare-pages, deploy-cloudflare-preview-worker, cloudflare-data]"
        in preview_job
    )
    assert "always()" in preview_job
    assert "needs.ci.result == 'success'" in preview_job
    assert "needs.deploy-cloudflare-pages.result == 'success'" in preview_job
    assert "needs.deploy-cloudflare-preview-worker.result == 'success'" in preview_job
    assert "needs.cloudflare-data.result == 'success'" in preview_job
    assert "needs.ci.outputs.deployment_environment == 'preview'" in preview_job
    assert (
        "API_URL: ${{ needs.deploy-cloudflare-preview-worker.outputs.preview_api_url }}"
        in preview_job
    )
    assert "PREVIEW_API_URL: ${{ vars.PREVIEW_API_URL }}" not in preview_job
    assert "API_URL: https://api.news-sentry.com" not in preview_job
    assert "Preview API_URL must point to a preview Worker runtime" in preview_job
    assert "https://api.news-sentry.com" in preview_job
    assert '"${API_URL}${path}"' in preview_job
    assert "fetch_preview_worker_receipt live /api/v1/live" in preview_job
    assert "fetch_preview_worker_receipt ready /api/v1/ready" in preview_job
    assert "fetch_preview_worker_receipt health /api/v1/health" in preview_job
    assert "x-news-sentry-deploy-commit" in preview_job
    assert "x-news-sentry-worker-version" in preview_job
    assert (
        "health.get(\"deployment\", {}).get(\"commit\") == os.environ[\"GITHUB_SHA\"]"
        in preview_job
    )


def test_preview_worker_deploy_job_is_isolated_and_exports_api_url() -> None:
    workflow = _workflow_text()
    preview_worker_job = workflow.split("  deploy-cloudflare-preview-worker:", 1)[1].split(
        "  deploy-cloudflare-pages:", 1
    )[0]

    assert "needs.ci.outputs.deployment_environment == 'preview'" in preview_worker_job
    assert "preview_api_url: ${{ steps.receipt.outputs.api_url }}" in preview_worker_job
    assert "node_modules/.bin/wrangler d1 list --json" in preview_worker_job
    assert "tools/cloudflare_preview_guard.py select-d1" in preview_worker_job
    assert "node_modules/.bin/wrangler d1 create ns-db-preview" in preview_worker_job
    assert "tools/cloudflare_preview_guard.py render-config" in preview_worker_job
    assert "--output frontend/cloudflare/wrangler.preview.generated.toml" in preview_worker_job
    assert "frontend/cloudflare/.generated" not in preview_worker_job
    assert "tools/cloudflare_preview_guard.py seed-sql" in preview_worker_job
    assert "node_modules/.bin/wrangler d1 execute DB" in preview_worker_job
    assert "--config wrangler.preview.generated.toml" in preview_worker_job
    assert "--env preview" in preview_worker_job
    assert (
        "node_modules/.bin/wrangler deploy --config "
        "wrangler.preview.generated.toml --env preview"
        in preview_worker_job
    )
    assert "tools/cloudflare_preview_guard.py deploy-receipt" in preview_worker_job
    assert "wrangler d1 delete" not in preview_worker_job
    assert "ns-db --remote" not in preview_worker_job
    assert "news-sentry-jobs" not in preview_worker_job


def test_preview_worker_deploy_injects_only_non_secret_access_vars() -> None:
    deploy_step = _step("deploy-cloudflare-preview-worker", "Deploy Cloudflare preview Worker")
    env = cast(dict[str, str], deploy_step["env"])
    script = str(deploy_step["run"])

    assert env["CF_ACCESS_TEAM_DOMAIN"] == "${{ vars.CF_ACCESS_TEAM_DOMAIN }}"
    assert env["CF_ACCESS_AUD"] == "${{ vars.CF_ACCESS_AUD }}"
    assert (
        env["CF_ACCESS_SERVICE_TOKEN_IDS"]
        == "${{ vars.CF_ACCESS_SERVICE_TOKEN_IDS }}"  # noqa: S105
    )
    assert "CF_ACCESS_CLIENT_SECRET" not in env

    required_vars = set(
        _shell_tokens(script, r': "\$\{(CF_ACCESS_[A-Z_]+):\?[^"]+\}"')
    )
    assert required_vars == {
        "CF_ACCESS_TEAM_DOMAIN",
        "CF_ACCESS_AUD",
        "CF_ACCESS_SERVICE_TOKEN_IDS",
    }

    wrangler_vars = set(_shell_tokens(script, r'--var "([^:"]+):'))
    assert {
        "NEWS_SENTRY_DEPLOY_COMMIT",
        "NEWS_SENTRY_ENVIRONMENT",
        "SCHEDULER_MODE",
        "WORKER_NATIVE_COLLECT_ENABLED",
        "CF_ACCESS_TEAM_DOMAIN",
        "CF_ACCESS_AUD",
        "CF_ACCESS_SERVICE_TOKEN_IDS",
    } <= wrangler_vars
    assert "CF_ACCESS_CLIENT_SECRET" not in wrangler_vars
    assert "set -x" not in script


def test_preview_worker_provisions_an_isolated_r2_artifact_bucket() -> None:
    workflow = _workflow_text()
    preview_worker_job = workflow.split("  deploy-cloudflare-preview-worker:", 1)[1].split(
        "  deploy-cloudflare-pages:", 1
    )[0]

    assert (
        "node_modules/.bin/wrangler r2 bucket info "
        "news-sentry-artifacts-preview --json" in preview_worker_job
    )
    assert (
        "node_modules/.bin/wrangler r2 bucket create news-sentry-artifacts-preview"
        in preview_worker_job
    )
    assert "news-sentry-artifacts-preview" in preview_worker_job


def test_verify_preview_uses_preview_environment_secrets_for_canary_only() -> None:
    verify_job = _job("verify-preview")
    env = cast(dict[str, str], verify_job["env"])

    assert verify_job["environment"] == "preview"
    assert "CF_ACCESS_CLIENT_ID" not in env
    assert "CF_ACCESS_CLIENT_SECRET" not in env

    canary_step = _step("verify-preview", "Run authenticated preview durable import canary")
    canary_env = cast(dict[str, str], canary_step["env"])
    assert canary_env["CF_ACCESS_CLIENT_ID"] == "${{ secrets.CF_ACCESS_CLIENT_ID }}"
    assert (
        canary_env["CF_ACCESS_CLIENT_SECRET"]
        == "${{ secrets.CF_ACCESS_CLIENT_SECRET }}"  # noqa: S105
    )

    for step in cast(list[dict[str, Any]], verify_job["steps"]):
        if step.get("name") == "Run authenticated preview durable import canary":
            continue
        step_env = cast(dict[str, str], step.get("env", {}))
        assert "CF_ACCESS_CLIENT_ID" not in step_env
        assert "CF_ACCESS_CLIENT_SECRET" not in step_env

    worker_job_text = yaml.dump(_job("deploy-cloudflare-preview-worker"))
    assert "CF_ACCESS_CLIENT_SECRET" not in worker_job_text
    assert "CF_ACCESS_CLIENT_ID" not in worker_job_text


def test_verify_preview_runs_authenticated_durable_import_canary_fail_closed() -> None:
    step_names = _step_names("verify-preview")
    assert step_names.index("Run authenticated preview durable import canary") < step_names.index(
        "Upload preview durable import canary receipt"
    )

    canary_step = _step("verify-preview", "Run authenticated preview durable import canary")
    script = str(canary_step["run"])

    helper_commands = _shell_tokens(
        script,
        r"tools/cloudflare_preview_canary\.py "
        r"(payload|evidence-sql|validate-artifact-key|receipt)",
    )
    assert helper_commands == ["payload", "evidence-sql", "validate-artifact-key", "receipt"]

    status_checks: dict[str, str] = dict(
        _shell_token_pairs(script, r'\[ "\$\{([A-Z_]+)\}" = "([0-9]+)" \]')
    )
    assert status_checks["ANON_STATUS"] == "403"
    assert status_checks["FIRST_STATUS"] == "200"
    assert status_checks["REPLAY_STATUS"] == "200"
    assert 'replay.get("replayed") is True' in script

    d1_targets = _shell_tokens(script, r"wrangler d1 execute ([a-z0-9-]+) --remote")
    assert d1_targets == ["ns-db-preview"]
    r2_gets = _shell_tokens(
        script,
        r'wrangler r2 object get "([a-z0-9-]+)/\$\{CANONICAL_ARTIFACT_KEY\}"',
    )
    assert r2_gets == ["news-sentry-artifacts-preview"]
    assert "--artifact-key \"${ARTIFACT_KEY}\"" in script
    assert (
        'CANONICAL_ARTIFACT_KEY="$(python tools/cloudflare_preview_canary.py '
        'validate-artifact-key --artifact-key "${ARTIFACT_KEY}")"'
    ) in script
    assert script.index("validate-artifact-key") < script.index("wrangler r2 object get")

    forbidden = (
        "ns-db --remote",
        "news-sentry-artifacts/${",
        "set -x",
        "Cf-Access-Jwt-Assertion",
        "Authorization:",
    )
    for token in forbidden:
        assert token not in script


def test_preview_canary_uploads_only_sanitized_receipt() -> None:
    upload = _step("verify-preview", "Upload preview durable import canary receipt")

    assert upload["uses"] == "actions/upload-artifact@v4"
    assert upload["with"] == {
        "name": "news-sentry-preview-artifact-canary-receipt",
        "path": "${{ runner.temp }}/news-sentry-preview-artifact-canary-receipt.json",
        "if-no-files-found": "error",
    }


def test_pages_preview_build_uses_preview_worker_output_but_main_can_skip_it() -> None:
    workflow = _workflow_text()
    pages_job = workflow.split("  deploy-cloudflare-pages:", 1)[1].split(
        "  verify-preview:", 1
    )[0]

    assert (
        "needs: [ci, cloudflare-data, deploy-cloudflare-worker, "
        "deploy-cloudflare-preview-worker]" in pages_job
    )
    assert "always()" in pages_job
    assert "needs.ci.result == 'success'" in pages_job
    assert "needs.deploy-cloudflare-preview-worker.result == 'success'" in pages_job
    assert "needs.deploy-cloudflare-worker.result == 'success'" in pages_job
    assert "needs.cloudflare-data.result == 'success'" in pages_job
    assert "needs.ci.outputs.deployment_environment == 'preview'" in pages_job
    assert (
        "needs.deploy-cloudflare-preview-worker.outputs.preview_api_url || "
        "'https://api.news-sentry.com' }}"
        in pages_job
    )
    assert (
        "VITE_API_BASE: ${{ needs.ci.outputs.deployment_environment == 'preview' &&"
        in pages_job
    )
    assert "Verify preview frontend API binding" in pages_job
    assert 'grep -F -- "${PREVIEW_API_URL}" dist/index.html' in pages_job
    assert 'grep -F -- "connect-src \'self\' ${PREVIEW_API_URL}" dist/_headers' in pages_job
    assert "Preview frontend leaked the production API origin" in pages_job
    assert 'branch="manual-preview-${GITHUB_RUN_ID}"' in pages_job
    assert "DEPLOYMENT_ENVIRONMENT: ${{ needs.ci.outputs.deployment_environment }}" in pages_job
    assert "Failed to extract the immutable Pages deployment URL" in pages_job
    assert 'pages_url="https://news-sentry.pages.dev"' not in pages_job
    assert "Install pinned Cloudflare deployment dependencies" in pages_job
    assert "../cloudflare/node_modules/.bin/wrangler pages deploy" in pages_job
    assert "npx wrangler pages deploy" not in pages_job
    assert "grep -F 'Deployment complete!'" in pages_job

    grep_match = re.search(r"grep -Eo '([^']+)'", pages_job)
    assert grep_match is not None
    assert grep_match.group(1) == r"https://[^[:space:]]+\.pages\.dev"
    sample_log = (
        "Deployment complete! Take a peek over at "
        "https://6180ce7e.news-sentry.pages.dev\n"
        "Deployment alias URL: "
        "https://manual-preview-123.news-sentry.pages.dev\n"
    )
    deployment_lines = "\n".join(
        line for line in sample_log.splitlines() if "Deployment complete!" in line
    )
    assert re.findall(r"https://\S+\.pages\.dev", deployment_lines) == [
        "https://6180ce7e.news-sentry.pages.dev"
    ]


def test_manual_preview_is_serialized_and_never_directly_promotes_main() -> None:
    workflow = _workflow_text()

    assert "concurrency:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "group: news-sentry-deploy\n" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "Reject production dispatch from non-main" in workflow
    assert "production dispatch is only allowed from refs/heads/main" in workflow
    assert "  promote-main:" not in workflow
    assert 'git push origin "${GITHUB_SHA}:refs/heads/main"' not in workflow


def test_main_push_cannot_trigger_production_deployment() -> None:
    workflow = _workflow()

    assert workflow["on"]["push"]["branches"] == ["preview"]


def test_production_dispatch_requires_exact_main_commit(tmp_path: Path) -> None:
    sha = "a" * 40
    wrong_sha = "b" * 40

    missing = _run_deployment_mode_script(
        tmp_path,
        event_name="workflow_dispatch",
        ref="refs/heads/main",
        sha=sha,
        requested_environment="production",
        expected_commit="",
    )
    wrong = _run_deployment_mode_script(
        tmp_path,
        event_name="workflow_dispatch",
        ref="refs/heads/main",
        sha=sha,
        requested_environment="production",
        expected_commit=wrong_sha,
    )
    exact = _run_deployment_mode_script(
        tmp_path,
        event_name="workflow_dispatch",
        ref="refs/heads/main",
        sha=sha,
        requested_environment="production",
        expected_commit=sha,
    )

    assert missing.returncode != 0
    assert "full 40-character commit SHA" in missing.stdout
    assert wrong.returncode != 0
    assert "does not match GITHUB_SHA" in wrong.stdout
    assert exact.returncode == 0, exact.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == "environment=production\n"


def test_production_jobs_require_main_and_preview_dispatch_stays_nonproduction() -> None:
    workflow = _workflow_text()
    production_worker_job = workflow.split("  deploy-cloudflare-worker:", 1)[1].split(
        "  deploy-cloudflare-preview-worker:", 1
    )[0]
    verify_production_job = workflow.split("  verify-production:", 1)[1]

    for job in (production_worker_job, verify_production_job):
        assert "needs.ci.outputs.deployment_environment == 'production'" in job

    cloudflare_data_job = workflow.split("  cloudflare-data:", 1)[1].split(
        "  deploy-cloudflare-worker:", 1
    )[0]
    assert "needs.ci.outputs.deployment_environment == 'preview'" in cloudflare_data_job
    assert "needs.ci.outputs.deployment_environment == 'production'" in cloudflare_data_job


def test_cloudflare_data_dry_run_has_one_output_sql_argument() -> None:
    workflow = _workflow_text()
    cloudflare_data_job = workflow.split("  cloudflare-data:", 1)[1].split(
        "  deploy-cloudflare-worker:", 1
    )[0]
    dry_run_step = cloudflare_data_job.split(
        "      - name: Cloudflare D1 backfill dry run", 1
    )[1].split("      - name:", 1)[0]

    assert dry_run_step.count("--output-sql /tmp/news-sentry-d1-backfill.sql") == 1


def test_production_data_job_applies_projection_receipt_migration() -> None:
    steps = _workflow()["jobs"]["cloudflare-data"]["steps"]
    named_steps = {
        step["name"]: (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, dict) and "name" in step
    }
    phase3_index, phase3_step = named_steps["Apply durable artifact manifest migration"]
    phase4_index, phase4_step = named_steps[
        "Apply projection import finalize receipt migration"
    ]

    assert phase3_index < phase4_index
    assert phase4_step["if"] == "needs.ci.outputs.deployment_environment == 'production'"
    assert phase4_step["working-directory"] == "frontend/cloudflare"
    assert phase4_step["run"].split() == [
        "node_modules/.bin/wrangler",
        "d1",
        "execute",
        "ns-db",
        "--remote",
        "--file=db/migrations/20260802_phase4_projection_import.sql",
    ]
    assert phase3_step["run"].split()[-1] == (
        "--file=db/migrations/20260802_phase3_durable_artifacts.sql"
    )
