from __future__ import annotations

from pathlib import Path

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
    default_targets = (
        'TARGETS="${NEWSSENTRY_REALTIME_TARGETS:-italy japan germany france china-watch-en}"'
    )

    assert "flock" in runner
    assert "news-sentry-realtime.lock" in runner
    assert default_targets in runner
    assert '--profile "${PROFILE}"' in runner
    assert "--stage all" in runner
    assert "/srv/news-sentry/production/data" in runner


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
