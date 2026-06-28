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
