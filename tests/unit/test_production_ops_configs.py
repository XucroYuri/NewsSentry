from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_realtime_systemd_service_uses_production_paths() -> None:
    service = (ROOT / "config/news-sentry-realtime.service").read_text(encoding="utf-8")

    assert "User=newssentry" in service
    assert "Group=newssentry" in service
    assert "WorkingDirectory=/opt/news-sentry/production/repo" in service
    assert "EnvironmentFile=/opt/news-sentry/production/.env" in service
    assert "ExecStart=/opt/news-sentry/production/repo/tools/run_realtime_collection.sh" in service
    assert "ReadWritePaths=/srv/news-sentry/production" in service
    assert "/opt/news-sentry/.venv" not in service
    assert "User=news-sentry" not in service


def test_realtime_runner_covers_active_targets_with_locking() -> None:
    runner = (ROOT / "tools/run_realtime_collection.sh").read_text(encoding="utf-8")
    collector = yaml.safe_load((ROOT / "config/runtime/collector.yaml").read_text(encoding="utf-8"))
    collector_targets = set(collector["target_ids"])

    assert "flock" in runner
    assert "news-sentry-realtime.lock" in runner
    assert (
        'COLLECTOR_CONFIG="${NEWSSENTRY_COLLECTOR_CONFIG:-${REPO_DIR}/config/runtime/'
        'collector.yaml}"'
    ) in runner
    assert 'TARGETS="${NEWSSENTRY_REALTIME_TARGETS:-' not in runner
    assert 'payload.get("target_ids")' in runner
    assert "--stage all" in runner
    assert '--profile "${PROFILE}"' in runner
    assert "NEWSSENTRY_REALTIME_BATCH_SIZE" in runner
    assert "realtime-target-cursor.txt" in runner
    assert "selected_targets" in runner
    assert "NEWSSENTRY_REALTIME_STRICT" in runner
    assert "/srv/news-sentry/production/data" in runner
    assert len(collector_targets) >= 70


def test_realtime_crontab_is_marked_legacy_fallback() -> None:
    crontab = (ROOT / "config/realtime.crontab").read_text(encoding="utf-8")

    assert "LEGACY FALLBACK" in crontab
    assert "/opt/news-sentry/production/repo" in crontab
    assert "/srv/news-sentry/production/data" in crontab
    assert "appuser" not in crontab
    assert "cd /app" not in crontab


def test_production_maintenance_crontab_covers_monitoring_and_backup() -> None:
    crontab = (ROOT / "config/production-maintenance.crontab").read_text(encoding="utf-8")

    assert "tools/health_monitor.sh --service news-sentry" in crontab
    assert "tools/backup.sh --data-dir /srv/news-sentry/production/data" in crontab
    assert "--backup-dir /srv/news-sentry/production/backup" in crontab
    assert "/srv/news-sentry/production/data/logs/health" in crontab
    assert "/srv/news-sentry/production/data/logs/backup" in crontab


def test_health_monitor_supports_systemd_service_mode() -> None:
    monitor = (ROOT / "tools/health_monitor.sh").read_text(encoding="utf-8")

    assert "--service NAME" in monitor
    assert "systemctl is-active" in monitor
    assert "SERVICE_STATUS" in monitor
    assert "service_status" in monitor


def test_deploy_workflow_gates_preview_before_main_promotion() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "FRONTEND_OUTPUT_SUBDIR: ${{ github.workspace }}/src/news_sentry/static" in workflow
    assert "Verify preview" in workflow
    assert "Promote main" in workflow
    assert "Verify production" in workflow
    assert "git merge-base --is-ancestor origin/main" in workflow
    assert "git push origin" in workflow
    assert "/api/v1/regions" in workflow
    assert "/api/v1/regions?include_empty=true" in workflow
    assert "/api/v1/public/news" in workflow
    assert "/public-app/" in workflow
    assert "x-news-sentry-deploy-commit" in workflow
    assert "--policy config/security/deployment-surface-policy.yaml" in workflow
    assert "CLOUDFLARE_STATE_JSON" in workflow
    assert "--cloudflare-state-json /tmp/news-sentry-cloudflare-state.json" in workflow


def test_deploy_workflow_keeps_web_service_out_of_auto_collection_path() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert 'upsert_env_kv "${DEPLOY_BASE}/${ENV}/.env" "NEWSSENTRY_AUTO_COLLECT" "0"' in workflow
    assert "for i in $(seq 1 24)" in workflow
    assert "Health check failed after 120s" in workflow


def test_deploy_workflow_enables_production_realtime_timer() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert (
        'upsert_env_kv "${DEPLOY_BASE}/${ENV}/.env" "NEWSSENTRY_REALTIME_BATCH_SIZE" "12"'
    ) in workflow
    assert 'upsert_env_kv "${DEPLOY_BASE}/${ENV}/.env" "NEWSSENTRY_REALTIME_STRICT" "0"' in workflow
    assert 'if [ "${ENV}" = "production" ]; then' in workflow
    assert "config/news-sentry-realtime.service" in workflow
    assert "config/news-sentry-realtime.timer" in workflow
    assert "systemctl enable --now news-sentry-realtime.timer" in workflow
    assert "systemctl start --no-block news-sentry-realtime.service" in workflow
    assert "Skipping realtime collection timer for ${ENV}" in workflow


def test_deploy_workflow_has_one_off_cloudflare_state_bypass_guard() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "allow_temporary_cloudflare_state_bypass" in workflow
    assert "TEMPORARY_CLOUDFLARE_STATE_BYPASS" in workflow
    assert "TEMPORARY_CLOUDFLARE_PREVIEW_ACCESS_BYPASS" in workflow
    assert "TEMPORARY_CLOUDFLARE_PRODUCTION_ENDPOINT_BYPASS" in workflow
    assert "SKIP_PRODUCTION_CF_PUBLIC_VERIFY" in workflow
    assert "[temporary-cloudflare-state-bypass]" in workflow
    assert "docs/deployment/cloudflare-state-json.example.json" in workflow
    assert "Missing CLOUDFLARE_STATE_JSON secret" in workflow
    assert "production deployed-surface audit requires Cloudflare state evidence" in workflow
