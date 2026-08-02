from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "cloudflare-restore-drill.yml"


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


def _target_step() -> dict[str, Any]:
    return next(
        step
        for step in _workflow()["jobs"]["restore-drill"]["steps"]
        if step.get("name") == "Resolve fail-closed restore target"
    )


def _run_target_step(
    tmp_path: Path,
    *,
    environment: str,
    expected_commit: str,
    sha: str,
    ref: str,
) -> subprocess.CompletedProcess[str]:
    output = tmp_path / "github-output"
    return subprocess.run(  # noqa: S603 - executes repository-owned workflow script.
        ["/bin/bash", "-c", _target_step()["run"]],
        check=False,
        capture_output=True,
        text=True,
        env={
            "EXPECTED_COMMIT": expected_commit,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REF": ref,
            "GITHUB_SHA": sha,
            "REQUESTED_ENVIRONMENT": environment,
            "PATH": "/usr/bin:/bin",
        },
    )


def test_restore_drill_is_manual_exact_sha_and_serialized() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["restore-drill"]

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert job["environment"] == "${{ inputs.environment }}"
    assert not any(key.startswith("CLOUDFLARE_") for key in job["env"])
    assert job["env"]["DRILL_DIR"] == "/tmp/news-sentry-restore-drill"  # noqa: S108
    assert "runner.temp" not in job["env"]["DRILL_DIR"]
    assert workflow["on"]["workflow_dispatch"]["inputs"]["expected_commit"]["required"] == "true"
    assert (
        workflow["on"]["workflow_dispatch"]["inputs"]["continuity_receipt"]["required"]
        == "true"
    )


def test_restore_drill_uses_only_isolated_recovery_surfaces() -> None:
    workflow = _workflow_text()

    assert 'd1 export "${SOURCE_DATABASE}" --remote' in workflow
    assert 'r2 object put "${object_path}" --remote' in workflow
    assert 'r2 object get "${object_path}" --remote' in workflow
    assert 'r2 bucket info "${BACKUP_BUCKET}" --json' in workflow
    assert 'r2 bucket create "${BACKUP_BUCKET}"' in workflow
    assert 'd1 create "${restore_database}"' in workflow
    assert 'd1 execute "${RESTORE_DATABASE}" --remote' in workflow
    assert 'd1 delete "${RESTORE_DATABASE}" --skip-confirmation' in workflow
    assert 'd1 list --json' in workflow
    restore_name = (
        'restore_database="ns-db-restore-drill-'
        '${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"'
    )
    assert restore_name in workflow
    assert "wrangler d1 time-travel restore" not in workflow.lower()
    assert 'd1 delete "ns-db"' not in workflow
    assert 'd1 delete "ns-db-preview"' not in workflow


def test_restore_drill_uploads_only_sanitized_receipt() -> None:
    workflow = _workflow_text()
    upload_step = workflow.split("      - name: Upload sanitized restore receipt", 1)[1]

    assert "restore-receipt.json" in upload_step
    assert "/tmp/news-sentry-restore-drill/restore-receipt.json" in upload_step  # noqa: S108
    assert "source-export.sql" not in upload_step
    assert "query-results.json" not in upload_step
    assert "artifact-receipts.json" not in upload_step
    assert "backup-receipt.json" not in upload_step
    assert "continuity-receipt.json" not in upload_step
    assert "restore_database_cleanup_failed" in workflow
    assert '"verified_absent": True' in workflow


def test_restore_drill_binds_restore_to_7d_continuity_receipt() -> None:
    workflow = _workflow_text()

    assert 'CONTINUITY_RECEIPT: ${{ inputs.continuity_receipt }}' in workflow
    assert 'payload.get("status") != "slo_7d_passed"' not in workflow
    assert 'payload.get("deployed_commit") != os.environ["EXPECTED_COMMIT"]' not in workflow
    assert "--expected-commit \"${EXPECTED_COMMIT}\"" in workflow
    assert '--continuity-receipt "${DRILL_DIR}/continuity-receipt.json"' in workflow
    assert (
        'printf \'%s\' "${CONTINUITY_RECEIPT}" > '
        '"${DRILL_DIR}/continuity-receipt.json"'
    ) in workflow


def test_restore_drill_uses_single_builder_and_always_writes_step_summary() -> None:
    workflow = _workflow_text()

    validate_step = workflow.split(
        "      - name: Validate restored D1 and R2 evidence", 1
    )[1].split("      - name: Delete isolated restore database", 1)[0]
    assert 'json.loads(os.environ["CONTINUITY_RECEIPT"])' not in validate_step
    assert "continuity receipt has not passed 7d SLO" not in validate_step
    assert "continuity receipt deployed_commit mismatch" not in validate_step
    assert "tools/cloudflare_restore_drill.py validate" in validate_step

    assert "      - name: Write restore drill summary" in workflow
    summary_step = workflow.split("      - name: Write restore drill summary", 1)[1].split(
        "      - name: Upload sanitized restore receipt", 1
    )[0]
    assert "if: always()" in summary_step
    assert "GITHUB_STEP_SUMMARY" in summary_step
    assert "restore_workflow_incomplete" in summary_step
    assert "summary.blockers" in summary_step


def test_restore_target_accepts_preview_and_rejects_sha_or_production_ref(
    tmp_path: Path,
) -> None:
    sha = "a" * 40
    preview = _run_target_step(
        tmp_path,
        environment="preview",
        expected_commit=sha,
        sha=sha,
        ref="refs/heads/dev-xu/fix/cloudflare-persistent-runtime",
    )
    assert preview.returncode == 0
    output = (tmp_path / "github-output").read_text(encoding="utf-8")
    assert "source_database=ns-db-preview" in output
    assert "artifact_bucket=news-sentry-artifacts-preview" in output
    assert "allow_missing_artifact=false" in output
    assert "backup_bucket=news-sentry-restore-drills-preview" in output
    assert f"expected_commit={sha}" in output

    mismatch = _run_target_step(
        tmp_path,
        environment="preview",
        expected_commit="b" * 40,
        sha=sha,
        ref="refs/heads/dev-xu/fix/cloudflare-persistent-runtime",
    )
    assert mismatch.returncode != 0

    production = _run_target_step(
        tmp_path,
        environment="production",
        expected_commit=sha,
        sha=sha,
        ref="refs/heads/dev-xu/fix/cloudflare-persistent-runtime",
    )
    assert production.returncode != 0
    assert "restricted to main" in production.stderr
