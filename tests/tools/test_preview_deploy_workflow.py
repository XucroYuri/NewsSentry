from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "deploy.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


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
    preview_job = workflow.split("  verify-preview:", 1)[1].split("  promote-main:", 1)[0]

    assert (
        "needs: [deploy-cloudflare-pages, deploy-cloudflare-preview-worker, cloudflare-data]"
        in preview_job
    )
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

    assert "if: github.ref == 'refs/heads/preview'" in preview_worker_job
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


def test_pages_preview_build_uses_preview_worker_output_but_main_can_skip_it() -> None:
    workflow = _workflow_text()
    pages_job = workflow.split("  deploy-cloudflare-pages:", 1)[1].split(
        "  verify-preview:", 1
    )[0]

    assert "needs: [ci, deploy-cloudflare-preview-worker]" in pages_job
    assert "always()" in pages_job
    assert "needs.ci.result == 'success'" in pages_job
    assert "needs.deploy-cloudflare-preview-worker.result == 'success'" in pages_job
    assert (
        "VITE_API_BASE: ${{ github.ref == 'refs/heads/preview' && "
        "needs.deploy-cloudflare-preview-worker.outputs.preview_api_url || "
        "'https://api.news-sentry.com' }}"
        in pages_job
    )
    assert "Verify preview frontend API binding" in pages_job
    assert 'grep -R -F -- "${PREVIEW_API_URL}" dist/' in pages_job
    assert 'if [ "${GITHUB_REF}" = "refs/heads/preview" ]; then' in pages_job
    assert "Failed to extract the immutable Pages preview deployment URL" in pages_job


def test_cloudflare_data_dry_run_has_one_output_sql_argument() -> None:
    workflow = _workflow_text()
    cloudflare_data_job = workflow.split("  cloudflare-data:", 1)[1].split(
        "  deploy-cloudflare-worker:", 1
    )[0]
    dry_run_step = cloudflare_data_job.split(
        "      - name: Cloudflare D1 backfill dry run", 1
    )[1].split("      - name:", 1)[0]

    assert dry_run_step.count("--output-sql /tmp/news-sentry-d1-backfill.sql") == 1
