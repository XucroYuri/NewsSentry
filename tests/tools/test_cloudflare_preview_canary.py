from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools import cloudflare_preview_canary as canary

COMMIT = "a" * 40
COMMIT_TIME = "2026-08-02T03:00:00+00:00"
SHA = "b" * 64
BATCH_CHECKSUM = "c" * 64
BATCH_ID = f"api-batch:{SHA}"
JOB_ID = f"api-job:{SHA}"
ARTIFACT_ID = f"artifact-{SHA}"
ARTIFACT_KEY = f"imports/v1/2026/08/02/{SHA}.json"
SECRET_MARKERS = (
    "CF-Access-Client-Secret",
    "Cf-Access-Jwt-Assertion",
    "jwt-token-value",
    "client-secret-value",
    "headers",
    "request_body",
)


def _response(*, replayed: bool) -> dict[str, object]:
    return {
        "imported": 1 if not replayed else 0,
        "updated": 0 if not replayed else 1,
        "skipped": 0,
        "quarantined": 0,
        "errors": [],
        "batch_id": BATCH_ID,
        "job_id": JOB_ID,
        "artifact_id": ARTIFACT_ID,
        "artifact_key": ARTIFACT_KEY,
        "artifact_sha256": SHA,
        "artifact_bytes": 16,
        "replayed": replayed,
        "headers": {"CF-Access-Client-Secret": "client-secret-value"},
        "request_body": [{"title_original": "must not leak"}],
    }


def _d1_row(*, artifact_bytes: int = 16, event_count: int = 1) -> dict[str, object]:
    return {
        "batch_id": BATCH_ID,
        "batch_status": "committed",
        "batch_count": 1,
        "job_id": JOB_ID,
        "job_status": "committed",
        "job_count": 1,
        "artifact_id": ARTIFACT_ID,
        "artifact_batch_id": BATCH_ID,
        "artifact_job_id": JOB_ID,
        "artifact_key": ARTIFACT_KEY,
        "artifact_sha256": SHA,
        "artifact_bytes": artifact_bytes,
        "artifact_status": "committed",
        "artifact_count": 1,
        "batch_checksum": BATCH_CHECKSUM,
        "projection_receipt_count": 1,
        "projection_batch_guard": BATCH_ID,
        "projection_job_guard": JOB_ID,
        "projection_artifact_guard": ARTIFACT_ID,
        "projection_batch_checksum": BATCH_CHECKSUM,
        "event_count": event_count,
    }


def test_payload_is_deterministic_for_preview_import() -> None:
    payload = canary.build_canary_payload(commit=COMMIT, commit_time=COMMIT_TIME)

    assert payload.idempotency_key == f"preview-artifact-canary:{COMMIT}"
    assert payload.event_id == "preview-artifact-canary-aaaaaaaaaaaa"
    assert payload.events == [
        {
            "collected_at": COMMIT_TIME,
            "content_original": "Deterministic Cloudflare preview artifact canary.",
            "event_id": "preview-artifact-canary-aaaaaaaaaaaa",
            "language": "en",
            "pipeline_stage": "collected",
            "source_id": "preview-canary-synthetic-source",
            "summary": "Synthetic event used to verify preview durable import receipts.",
            "target_id": "preview-canary",
            "title_original": "News Sentry Preview Artifact Canary aaaaaaaaaaaa",
            "url": "https://example.test/news-sentry/preview-artifact-canary-aaaaaaaaaaaa",
        }
    ]
    rendered = json.dumps(payload.__dict__, ensure_ascii=False, sort_keys=True)
    assert rendered == json.dumps(
        canary.build_canary_payload(commit=COMMIT, commit_time=COMMIT_TIME).__dict__,
        ensure_ascii=False,
        sort_keys=True,
    )


def test_evidence_sql_validates_canonical_ids_and_counts_all_receipts() -> None:
    sql = canary.build_evidence_sql(
        batch_id=BATCH_ID,
        job_id=JOB_ID,
        artifact_id=ARTIFACT_ID,
    )

    assert "import_batches" in sql
    assert "jobs" in sql
    assert "artifact_manifests" in sql
    assert "import_projection_finalize_receipts" in sql
    assert "import_staged_events" in sql
    assert "COUNT(*) AS batch_count" in sql
    assert "COUNT(*) AS projection_receipt_count" in sql
    assert "COUNT(*) AS event_count" in sql
    assert "batch.checksum AS batch_checksum" in sql
    assert "artifact.batch_id = expected.batch_id" in sql
    assert "artifact.job_id = expected.job_id" in sql
    assert (
        "WHERE artifact_id = expected.artifact_id\n"
        "      AND batch_id = expected.batch_id\n"
        "      AND job_id = expected.job_id"
    ) in sql

    with pytest.raises(canary.PreviewCanaryError, match="batch_id_invalid"):
        canary.build_evidence_sql(
            batch_id=f"{BATCH_ID}' OR 1=1 --",
            job_id=JOB_ID,
            artifact_id=ARTIFACT_ID,
        )


def test_receipt_cross_checks_response_d1_and_r2_without_secret_passthrough(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"x" * 16)
    artifact_sha = hashlib.sha256(b"x" * 16).hexdigest()
    row = _d1_row()
    row["artifact_sha256"] = artifact_sha
    row["artifact_key"] = f"imports/v1/2026/08/02/{artifact_sha}.json"
    first = _response(replayed=False)
    replay = _response(replayed=True)
    for response in (first, replay):
        response["artifact_sha256"] = artifact_sha
        response["artifact_key"] = row["artifact_key"]

    receipt = canary.build_canary_receipt(
        deploy_commit=COMMIT,
        first_response=first,
        replay_response=replay,
        d1_rows=[row],
        artifact_path=artifact,
    )

    assert receipt["status"] == "ok"
    assert receipt["gate_status"] == "preview_gate0_passed"
    assert receipt["deployed_commit"] == COMMIT
    assert receipt["source_environment"] == "preview"
    assert receipt["source_runtime"] == "cloudflare-worker"
    assert receipt["identity"] == {
        "batch_id": BATCH_ID,
        "job_id": JOB_ID,
        "artifact_id": ARTIFACT_ID,
    }
    assert receipt["counts"] == {
        "artifact": 1,
        "batch": 1,
        "event": 1,
        "job": 1,
        "projection_receipt": 1,
    }
    assert receipt["artifact"] == {
        "bytes": 16,
        "key": row["artifact_key"],
        "sha256": artifact_sha,
        "status": "committed",
    }
    assert receipt["responses"] == {
        "first": {"status": "committed", "replayed": False},
        "replay": {"status": "committed", "replayed": True},
    }
    rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    for marker in SECRET_MARKERS:
        assert marker not in rendered


def test_receipt_fails_closed_on_missing_or_inconsistent_evidence(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"x" * 16)

    missing = canary.build_canary_receipt(
        deploy_commit=COMMIT,
        first_response=_response(replayed=False),
        replay_response=_response(replayed=True),
        d1_rows=[],
        artifact_path=artifact,
    )
    assert missing["status"] == "failed"
    assert "d1_row_count_invalid" in missing["blockers"]

    mismatched = canary.build_canary_receipt(
        deploy_commit=COMMIT,
        first_response=_response(replayed=False),
        replay_response=_response(replayed=True),
        d1_rows=[_d1_row(artifact_bytes=17)],
        artifact_path=artifact,
    )
    assert mismatched["status"] == "failed"
    assert "artifact_bytes_mismatch" in mismatched["blockers"]


def test_receipt_compares_projection_checksum_to_batch_checksum(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"x" * 16)
    artifact_sha = hashlib.sha256(b"x" * 16).hexdigest()
    row = _d1_row()
    row["artifact_sha256"] = artifact_sha
    row["artifact_key"] = f"imports/v1/2026/08/02/{artifact_sha}.json"
    row["batch_checksum"] = BATCH_CHECKSUM
    row["projection_batch_checksum"] = BATCH_CHECKSUM
    first = _response(replayed=False)
    replay = _response(replayed=True)
    for response in (first, replay):
        response["artifact_sha256"] = artifact_sha
        response["artifact_key"] = row["artifact_key"]

    receipt = canary.build_canary_receipt(
        deploy_commit=COMMIT,
        first_response=first,
        replay_response=replay,
        d1_rows=[row],
        artifact_path=artifact,
    )

    assert receipt["status"] == "ok"


def test_receipt_fails_when_artifact_manifest_belongs_to_different_import(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"x" * 16)
    artifact_sha = hashlib.sha256(b"x" * 16).hexdigest()
    row = _d1_row()
    row["artifact_sha256"] = artifact_sha
    row["artifact_key"] = f"imports/v1/2026/08/02/{artifact_sha}.json"
    row["artifact_batch_id"] = f"api-batch:{'d' * 64}"
    row["artifact_job_id"] = f"api-job:{'e' * 64}"
    first = _response(replayed=False)
    replay = _response(replayed=True)
    for response in (first, replay):
        response["artifact_sha256"] = artifact_sha
        response["artifact_key"] = row["artifact_key"]

    receipt = canary.build_canary_receipt(
        deploy_commit=COMMIT,
        first_response=first,
        replay_response=replay,
        d1_rows=[row],
        artifact_path=artifact,
    )

    assert receipt["status"] == "failed"
    assert "artifact_batch_id_mismatch" in receipt["blockers"]
    assert "artifact_job_id_mismatch" in receipt["blockers"]


def test_parse_wrangler_d1_json_prefers_wrapped_results_after_noise() -> None:
    wrapped = "wrangler noise\n" + json.dumps(
        [{"success": True, "results": [{"batch_id": BATCH_ID}]}]
    )

    assert canary.parse_wrangler_d1_json(wrapped) == [{"batch_id": BATCH_ID}]


def test_artifact_key_validation_emits_only_canonical_key() -> None:
    assert canary.canonical_artifact_key(ARTIFACT_KEY) == ARTIFACT_KEY

    invalid_keys = [
        f" {ARTIFACT_KEY}",
        f"{ARTIFACT_KEY}\n",
        f"{ARTIFACT_KEY} ",
        f"{ARTIFACT_KEY} --file /tmp/leak.json",
        "--help",
        "../artifact.json",
        f"news-sentry-artifacts-preview/{ARTIFACT_KEY}",
        f"{ARTIFACT_KEY}/extra",
    ]
    for value in invalid_keys:
        with pytest.raises(canary.PreviewCanaryError, match="artifact_key_invalid"):
            canary.canonical_artifact_key(value)


def test_artifact_key_cli_rejects_response_json_value_after_shell_substitution(
    tmp_path: Path,
) -> None:
    response_path = tmp_path / "first-response.json"
    response_path.write_text(
        json.dumps({"artifact_key": f"{ARTIFACT_KEY}\n"}),
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - regression runs repository-owned helper.
        [
            "/bin/bash",
            "-c",
            (
                'artifact_key="$(python -c \'import json,sys; '
                'print(json.load(open(sys.argv[1]))["artifact_key"])\' "$1")"\n'
                "python tools/cloudflare_preview_canary.py validate-artifact-key "
                '--artifact-key "${artifact_key}"'
            ),
            "bash",
            str(response_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""


def test_cli_subcommands_emit_canonical_json_and_failed_receipts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert canary.main(["payload", "--commit", COMMIT, "--commit-time", COMMIT_TIME]) == 0
    payload_stdout = capsys.readouterr().out
    payload_cli = json.loads(payload_stdout)
    assert payload_cli["api_url"] == (
        "https://news-sentry-api-preview.xuyu.workers.dev/api/v1/events/import"
    )
    assert payload_cli["idempotency_key"] == f"preview-artifact-canary:{COMMIT}"
    assert payload_stdout == json.dumps(json.loads(payload_stdout), sort_keys=True) + "\n"

    assert (
        canary.main(
            [
                "evidence-sql",
                "--batch-id",
                BATCH_ID,
                "--job-id",
                JOB_ID,
                "--artifact-id",
                ARTIFACT_ID,
            ]
        )
        == 0
    )
    assert "FROM import_batches" in capsys.readouterr().out

    valid_response_path = tmp_path / "valid-first-response.json"
    valid_response_path.write_text(
        json.dumps({"artifact_key": ARTIFACT_KEY}),
        encoding="utf-8",
    )
    assert (
        canary.main(
            [
                "validate-artifact-key",
                "--first-response",
                str(valid_response_path),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == f"{ARTIFACT_KEY}\n"

    invalid_response_path = tmp_path / "invalid-first-response.json"
    invalid_response_path.write_text(
        json.dumps({"artifact_key": f"{ARTIFACT_KEY}\n"}),
        encoding="utf-8",
    )
    assert (
        canary.main(
            [
                "validate-artifact-key",
                "--first-response",
                str(invalid_response_path),
            ]
        )
        == 2
    )
    invalid_cli = capsys.readouterr()
    assert invalid_cli.out == ""
    assert "artifact_key_invalid" in invalid_cli.err

    malformed_response_path = tmp_path / "malformed-first-response.json"
    malformed_response_path.write_text("{not-json", encoding="utf-8")
    assert (
        canary.main(
            [
                "validate-artifact-key",
                "--first-response",
                str(malformed_response_path),
            ]
        )
        == 2
    )
    malformed_cli = capsys.readouterr()
    assert malformed_cli.out == ""
    assert "artifact_key_invalid" in malformed_cli.err

    first_path = tmp_path / "first.json"
    replay_path = tmp_path / "replay.json"
    rows_path = tmp_path / "rows.json"
    artifact = tmp_path / "artifact.json"
    output = tmp_path / "receipt.json"
    first_path.write_text(json.dumps(_response(replayed=False)), encoding="utf-8")
    replay_path.write_text(json.dumps(_response(replayed=True)), encoding="utf-8")
    rows_path.write_text(json.dumps([_d1_row()]), encoding="utf-8")
    artifact.write_bytes(b"x" * 16)

    code = canary.main(
        [
            "receipt",
            "--deploy-commit",
            COMMIT,
            "--first-response",
            str(first_path),
            "--replay-response",
            str(replay_path),
            "--d1-json",
            str(rows_path),
            "--artifact",
            str(artifact),
            "--output",
            str(output),
        ]
    )

    assert code == 2
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert "artifact_sha256_mismatch" in receipt["blockers"]


def test_deploy_workflow_passes_exact_commit_to_preview_canary_receipt() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/deploy.yml"
    ).read_text(encoding="utf-8")
    canary_step = workflow.split(
        "      - name: Run authenticated preview durable import canary", 1
    )[1].split("      - name: Upload preview durable import canary receipt", 1)[0]

    assert "python tools/cloudflare_preview_canary.py receipt" in canary_step
    assert '--deploy-commit "${GITHUB_SHA}"' in canary_step


def test_receipt_cli_requires_explicit_deploy_commit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first_path = tmp_path / "first.json"
    replay_path = tmp_path / "replay.json"
    rows_path = tmp_path / "rows.json"
    artifact = tmp_path / "artifact.json"
    first_path.write_text(json.dumps(_response(replayed=False)), encoding="utf-8")
    replay_path.write_text(json.dumps(_response(replayed=True)), encoding="utf-8")
    rows_path.write_text(json.dumps([_d1_row()]), encoding="utf-8")
    artifact.write_bytes(b"x" * 16)

    with pytest.raises(SystemExit) as error:
        canary.main(
            [
                "receipt",
                "--first-response",
                str(first_path),
                "--replay-response",
                str(replay_path),
                "--d1-json",
                str(rows_path),
                "--artifact",
                str(artifact),
            ]
        )

    assert error.value.code == 2
    assert "deploy-commit" in capsys.readouterr().err
