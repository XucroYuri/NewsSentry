from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "deploy.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _extract_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_deploy_workflow_env_template_allows_external_data_dir() -> None:
    workflow = _workflow_text()
    env_template = _extract_block(
        workflow,
        "cat > \"${DEPLOY_BASE}/${ENV}/.env\" <<'ENVEOF'\n",
        "\n            ENVEOF",
    )

    assert "NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR=1" in env_template


def test_deploy_workflow_systemd_service_allows_external_data_dir() -> None:
    workflow = _workflow_text()
    systemd_unit = _extract_block(
        workflow,
        "cat > \"/etc/systemd/system/${SERVICE}.service\" <<SVCEOF\n",
        "\n            SVCEOF",
    )

    assert "Environment=NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR=1" in systemd_unit
