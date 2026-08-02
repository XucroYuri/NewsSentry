from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS

from tools import cloudflare_preview_canary as canary
from tools import cloudflare_restore_drill as drill

SHA_A = "a" * 64
SHA_B = "b" * 64
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
BODY = "restore export body that must never appear in receipts"
ARTIFACT_KEY = f"imports/v1/2026/08/02/{SHA_A}.json"
BACKUP_KEY = "restore-drills/v1/production/20260802-1.sql"
PREVIEW_BACKUP_KEY = "restore-drills/v1/preview/20260802-1.sql"


class FakeRunner:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        return self.response


def _snapshot(key: str, payload: object) -> dict[str, Any]:
    payload_json = json.dumps(payload, separators=(",", ":"))
    return {
        "key": key,
        "payload_json": payload_json,
        "payload_bytes": len(payload_json.encode("utf-8")),
        "item_count": 1,
    }


def _good_query_results() -> dict[str, list[dict[str, Any]]]:
    return {
        "tables": [{"name": table} for table in sorted(drill.REQUIRED_TABLES)],
        "indexes": [{"name": index} for index in sorted(drill.REQUIRED_INDEXES)],
        "migration_receipts": [
            {"migration_id": receipt_id}
            for receipt_id in EXPECTED_MIGRATION_RECEIPTS
        ],
        "row_counts": [
            {"table": "events", "row_count": 12},
            {"table": "targets", "row_count": 3},
            {"table": "public_read_snapshots", "row_count": 5},
            {
                "table": "runtime_migration_receipts",
                "row_count": len(EXPECTED_MIGRATION_RECEIPTS),
            },
        ],
        "artifact_manifests": [
            {
                "artifact_id": "artifact-1",
                "batch_id": "batch-1",
                "job_id": "job-1",
                "object_key": ARTIFACT_KEY,
                "sha256": SHA_A,
                "payload_bytes": 48,
                "status": "committed",
                "deploy_commit": COMMIT_A,
                "source_environment": "production",
                "source_runtime": "cloudflare-container",
                "task": "container-import",
                "projection_origin": "container-import",
                "details_json": json.dumps({"note": BODY}),
            }
        ],
        "real_artifact_proof": [
            {
                "real_event_count": 1,
                "synthetic_event_count": 0,
                "deploy_commit": COMMIT_A,
                "source_environment": "production",
                "source_runtime": "cloudflare-container",
                "task": "container-import",
                "projection_origin": "container-import",
            }
        ],
        "orphan_counts": [
            {
                "artifact_manifest_orphans": 0,
                "artifact_batch_orphans": 0,
                "staged_event_orphans": 0,
                "finalize_receipt_orphans": 0,
                "projection_finalize_receipt_orphans": 0,
                "projection_job_orphans": 0,
                "projection_artifact_orphans": 0,
                "finalize_receipt_conflicts": 0,
                "projection_guard_mismatches": 0,
            }
        ],
        "artifact_status_counts": [{"stored_count": 0, "failed_count": 0}],
        "future_residual_counts": [
            {"future_collected_count": 0, "future_published_count": 0}
        ],
        "public_snapshots": [
            _snapshot("news:featured:v1:page_size=20", {"items": [{"id": "event-1"}]}),
            _snapshot("news:all:v1:page_size=20", {"items": [{"id": "event-1"}]}),
            _snapshot("bootstrap:featured:v1:page_size=20", {"news": {"items": []}}),
            _snapshot("facets:v1", {"regions": []}),
            _snapshot("regions:active:v1", {"regions": []}),
        ],
    }


def _good_artifact_receipts() -> dict[str, dict[str, Any]]:
    return {ARTIFACT_KEY: {"sha256": SHA_A, "bytes": 48}}


def _good_backup_receipt() -> dict[str, Any]:
    return {
        "object_key": BACKUP_KEY,
        "uploaded": {"sha256": SHA_B, "bytes": 1024},
        "downloaded": {"sha256": SHA_B, "bytes": 1024},
    }


def _preview_backup_receipt() -> dict[str, Any]:
    return {
        "object_key": PREVIEW_BACKUP_KEY,
        "uploaded": {"sha256": SHA_B, "bytes": 1024},
        "downloaded": {"sha256": SHA_B, "bytes": 1024},
    }


def synthetic_only_query_results() -> dict[str, list[dict[str, Any]]]:
    query_results = _good_query_results()
    query_results["real_artifact_proof"] = [
        {"real_event_count": 0, "synthetic_event_count": 1}
    ]
    return query_results


def preview_query_results() -> dict[str, list[dict[str, Any]]]:
    query_results = _good_query_results()
    preview_values = {
        "source_environment": "preview",
        "source_runtime": "cloudflare-worker",
        "task": "api-import",
        "projection_origin": "api-import",
    }
    for key, value in preview_values.items():
        query_results["artifact_manifests"][0][key] = value
        query_results["real_artifact_proof"][0][key] = value
    query_results["real_artifact_proof"][0]["real_event_count"] = 0
    query_results["real_artifact_proof"][0]["synthetic_event_count"] = 1
    return query_results


def provenance_query_results(**overrides: str) -> dict[str, list[dict[str, Any]]]:
    query_results = _good_query_results()
    for key, value in overrides.items():
        query_results["artifact_manifests"][0][key] = value
        query_results["real_artifact_proof"][0][key] = value
    return query_results


def _receipt(
    query_results: dict[str, list[dict[str, Any]]] | None = None,
    artifact_receipts: dict[str, dict[str, Any]] | None = None,
    backup_receipt: dict[str, Any] | None = None,
    expected_commit: str = COMMIT_A,
    continuity_receipt: dict[str, Any] | None = None,
    require_artifact: bool = True,
    source_environment: str = "production",
) -> dict[str, Any]:
    return drill.build_restore_receipt(
        database="ns-db-restore-drill-20260802-1",
        source_environment=source_environment,
        expected_commit=expected_commit,
        continuity_receipt=(
            continuity_receipt
            if continuity_receipt is not None
            else {"status": "slo_7d_passed", "deployed_commit": expected_commit}
        ),
        query_results=query_results if query_results is not None else _good_query_results(),
        artifact_receipts=(
            artifact_receipts
            if artifact_receipts is not None
            else _good_artifact_receipts()
        ),
        backup_receipt=(
            backup_receipt if backup_receipt is not None else _good_backup_receipt()
        ),
        require_artifact=require_artifact,
    )


def test_restore_drill_success_sanitizes_receipt_body() -> None:
    receipt = _receipt()

    assert receipt["status"] == "ok"
    assert receipt["source_environment"] == "production"
    assert receipt["evidence_class"] == "production_real_artifact"
    assert receipt["expected_commit"] == COMMIT_A
    assert receipt["continuity_receipt"] == {
        "status": "slo_7d_passed",
        "deployed_commit": COMMIT_A,
    }
    assert receipt["summary"]["blockers"] == []
    rendered = json.dumps(receipt, ensure_ascii=False)
    assert BODY not in rendered
    assert "payload_json" not in rendered
    assert "path" not in receipt["evidence"]["backup_roundtrip"]
    assert receipt["summary"]["artifact_coverage"] == "verified"
    assert receipt["evidence"]["backup_roundtrip"] == {
        "object_key": BACKUP_KEY,
        "sha256": SHA_B,
        "bytes": 1024,
    }
    assert receipt["evidence"]["artifact_manifests"] == [
        {
            "object_key": ARTIFACT_KEY,
            "sha256": SHA_A,
            "bytes": 48,
            "status": "committed",
            "deploy_commit": COMMIT_A,
            "source_environment": "production",
            "source_runtime": "cloudflare-container",
            "task": "container-import",
            "projection_origin": "container-import",
        }
    ]


def test_restore_drill_accepts_preview_gate0_synthetic_canary_contract() -> None:
    receipt = _receipt(
        query_results=preview_query_results(),
        backup_receipt=_preview_backup_receipt(),
        continuity_receipt={"status": "preview_gate0_passed", "deployed_commit": COMMIT_A},
        source_environment="preview",
    )

    assert receipt["status"] == "ok"
    assert receipt["source_environment"] == "preview"
    assert receipt["evidence_class"] == "preview_synthetic_canary"
    assert receipt["continuity_receipt"]["status"] == "preview_gate0_passed"
    assert receipt["evidence"]["real_artifact_proof"] == {
        "deploy_commit": COMMIT_A,
        "projection_origin": "api-import",
        "real_event_count": 0,
        "source_environment": "preview",
        "source_runtime": "cloudflare-worker",
        "synthetic_event_count": 1,
        "task": "api-import",
    }


def test_restore_drill_accepts_real_preview_canary_receipt_without_wrapper(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"x" * 48)
    artifact_sha = hashlib.sha256(b"x" * 48).hexdigest()
    first = {
        "batch_id": f"api-batch:{SHA_A}",
        "job_id": f"api-job:{SHA_A}",
        "artifact_id": f"artifact-{SHA_A}",
        "artifact_key": f"imports/v1/2026/08/02/{artifact_sha}.json",
        "artifact_sha256": artifact_sha,
        "artifact_bytes": 48,
        "errors": [],
        "replayed": False,
    }
    replay = {**first, "replayed": True}
    d1_row = {
        "batch_id": first["batch_id"],
        "batch_status": "committed",
        "batch_count": 1,
        "batch_checksum": SHA_B,
        "job_id": first["job_id"],
        "job_status": "committed",
        "job_count": 1,
        "artifact_id": first["artifact_id"],
        "artifact_batch_id": first["batch_id"],
        "artifact_job_id": first["job_id"],
        "artifact_key": first["artifact_key"],
        "artifact_sha256": artifact_sha,
        "artifact_bytes": 48,
        "artifact_status": "committed",
        "artifact_count": 1,
        "projection_receipt_count": 1,
        "projection_batch_guard": first["batch_id"],
        "projection_job_guard": first["job_id"],
        "projection_artifact_guard": first["artifact_id"],
        "projection_batch_checksum": SHA_B,
        "event_count": 1,
    }
    continuity_receipt = canary.build_canary_receipt(
        deploy_commit=COMMIT_A,
        first_response=first,
        replay_response=replay,
        d1_rows=[d1_row],
        artifact_path=artifact,
    )

    query_results = preview_query_results()
    query_results["artifact_manifests"][0]["object_key"] = first["artifact_key"]
    query_results["artifact_manifests"][0]["sha256"] = artifact_sha
    query_results["artifact_manifests"][0]["payload_bytes"] = 48

    preview = _receipt(
        query_results=query_results,
        backup_receipt=_preview_backup_receipt(),
        artifact_receipts={str(first["artifact_key"]): {"sha256": artifact_sha, "bytes": 48}},
        continuity_receipt=continuity_receipt,
        source_environment="preview",
    )
    production = _receipt(
        query_results=query_results,
        backup_receipt=_preview_backup_receipt(),
        artifact_receipts={str(first["artifact_key"]): {"sha256": artifact_sha, "bytes": 48}},
        continuity_receipt=continuity_receipt,
        source_environment="production",
    )

    assert continuity_receipt["status"] == "ok"
    assert continuity_receipt["gate_status"] == "preview_gate0_passed"
    assert continuity_receipt["deployed_commit"] == COMMIT_A
    assert preview["status"] == "ok"
    assert production["status"] == "failed"
    assert "continuity_slo_7d_not_passed" in production["summary"]["blockers"]


def test_restore_drill_rejects_preview_contract_for_production() -> None:
    receipt = _receipt(
        query_results=preview_query_results(),
        backup_receipt=_preview_backup_receipt(),
        continuity_receipt={"status": "preview_gate0_passed", "deployed_commit": COMMIT_A},
        source_environment="production",
    )

    assert receipt["status"] == "failed"
    assert "continuity_slo_7d_not_passed" in receipt["summary"]["blockers"]
    assert "artifact_provenance_not_production" in receipt["summary"]["blockers"]
    assert "backup_source_environment_mismatch:preview" in receipt["summary"]["blockers"]


def test_restore_drill_rejects_production_contract_for_preview() -> None:
    receipt = _receipt(
        continuity_receipt={"status": "slo_7d_passed", "deployed_commit": COMMIT_A},
        source_environment="preview",
    )

    assert receipt["status"] == "failed"
    assert "continuity_preview_gate0_not_passed" in receipt["summary"]["blockers"]
    assert "artifact_provenance_not_preview" in receipt["summary"]["blockers"]
    assert "backup_source_environment_mismatch:production" in receipt["summary"][
        "blockers"
    ]


def test_restore_drill_rejects_backup_object_key_environment_mismatch() -> None:
    receipt = _receipt(backup_receipt=_preview_backup_receipt())

    assert receipt["status"] == "failed"
    assert "backup_source_environment_mismatch:preview" in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_on_future_timestamp_residuals() -> None:
    query_results = _good_query_results()
    query_results["future_residual_counts"] = [
        {"future_collected_count": 1, "future_published_count": 2}
    ]

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert "future_timestamp_residual_nonzero:collected=1,published=2" in receipt[
        "summary"
    ]["blockers"]
    assert receipt["evidence"]["future_residual_counts"] == {
        "future_collected_count": 1,
        "future_published_count": 2,
    }


def test_restore_rejects_continuity_commit_mismatch() -> None:
    receipt = _receipt(
        expected_commit=COMMIT_B,
        continuity_receipt={"status": "slo_7d_passed", "deployed_commit": COMMIT_A},
    )

    assert receipt["status"] == "failed"
    assert "continuity_commit_mismatch" in receipt["summary"]["blockers"]


def test_restore_requires_real_committed_artifact_after_canary() -> None:
    receipt = _receipt(
        query_results=synthetic_only_query_results(),
        expected_commit=COMMIT_A,
        continuity_receipt={"status": "slo_7d_passed", "deployed_commit": COMMIT_A},
    )

    assert receipt["status"] == "failed"
    assert "real_committed_artifact_missing" in receipt["summary"]["blockers"]


@pytest.mark.parametrize(
    ("name", "query_results", "blocker"),
    [
        (
            "synthetic provenance with ordinary artifact name",
            provenance_query_results(task="synthetic-canary"),
            "artifact_provenance_not_container_import",
        ),
        (
            "preview provenance",
            provenance_query_results(source_environment="preview"),
            "artifact_provenance_not_production",
        ),
        (
            "local provenance",
            provenance_query_results(source_runtime="local-sqlite"),
            "artifact_provenance_not_cloudflare_container",
        ),
        (
            "unknown provenance",
            provenance_query_results(source_environment="unknown"),
            "artifact_provenance_not_production",
        ),
        (
            "missing provenance",
            provenance_query_results(source_environment=""),
            "artifact_provenance_not_production",
        ),
        (
            "wrong commit provenance",
            provenance_query_results(deploy_commit=COMMIT_B),
            f"artifact_commit_mismatch:{ARTIFACT_KEY}",
        ),
    ],
)
def test_restore_requires_positive_production_container_artifact_provenance(
    name: str,
    query_results: dict[str, list[dict[str, Any]]],
    blocker: str,
) -> None:
    del name

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert blocker in receipt["summary"]["blockers"]


def test_restore_accepts_matching_production_container_artifact_provenance() -> None:
    receipt = _receipt(query_results=provenance_query_results())

    assert receipt["status"] == "ok"
    assert receipt["evidence"]["real_artifact_proof"] == {
        "deploy_commit": COMMIT_A,
        "projection_origin": "container-import",
        "real_event_count": 1,
        "source_environment": "production",
        "source_runtime": "cloudflare-container",
        "synthetic_event_count": 0,
        "task": "container-import",
    }


def test_restore_requires_7d_slo_continuity_receipt() -> None:
    receipt = _receipt(
        continuity_receipt={"status": "canary_72h_passed", "deployed_commit": COMMIT_A},
    )

    assert receipt["status"] == "failed"
    assert "continuity_slo_7d_not_passed" in receipt["summary"]["blockers"]


def test_restore_rejects_artifact_commit_mismatch() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"][0]["deploy_commit"] = COMMIT_B

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert f"artifact_commit_mismatch:{ARTIFACT_KEY}" in receipt["summary"]["blockers"]


def test_restore_database_name_rejects_production_names_and_injection() -> None:
    assert (
        drill.validate_restore_database_name("ns-db-restore-drill-20260802-1")
        == "ns-db-restore-drill-20260802-1"
    )

    for name in ("ns-db", "ns-db-preview", "ns-db-dev"):
        with pytest.raises(drill.RestoreDrillError, match="protected_restore_database"):
            drill.validate_restore_database_name(name)

    with pytest.raises(drill.RestoreDrillError, match="restore_database_name_invalid"):
        drill.validate_restore_database_name("ns-db-restore-drill-1-2; DROP TABLE events")

    runner = FakeRunner(json.dumps([{"results": [{"ok": 1}]}]))
    with pytest.raises(drill.RestoreDrillError, match="restore_database_name_invalid"):
        drill.run_wrangler_d1_query(
            wrangler="wrangler",
            database="ns-db-restore-drill-1-2 --remote",
            sql="SELECT 1",
            remote=True,
            runner=runner,
        )
    assert runner.calls == []


def test_parse_wrangler_d1_json_supports_wrapped_output_and_runner_command() -> None:
    assert drill.parse_wrangler_d1_json(
        "noise\n" + json.dumps([{"success": True, "results": [{"name": "events"}]}])
    ) == [{"name": "events"}]

    runner = FakeRunner(json.dumps({"results": [{"count": 1}]}))
    rows = drill.run_wrangler_d1_query(
        wrangler="wrangler-bin",
        database="ns-db-restore-drill-20260802-2",
        sql="SELECT COUNT(*) AS count FROM events",
        remote=False,
        runner=runner,
    )

    assert rows == [{"count": 1}]
    assert runner.calls == [
        [
            "wrangler-bin",
            "d1",
            "execute",
            "ns-db-restore-drill-20260802-2",
            "--command",
            "SELECT COUNT(*) AS count FROM events",
            "--json",
            "--local",
        ]
    ]


def test_restore_drill_fails_closed_on_missing_table() -> None:
    query_results = _good_query_results()
    query_results["tables"] = [
        row for row in query_results["tables"] if row["name"] != "artifact_manifests"
    ]

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert "schema_table_missing:artifact_manifests" in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_on_missing_migration_receipt() -> None:
    query_results = _good_query_results()
    missing = EXPECTED_MIGRATION_RECEIPTS[0]
    query_results["migration_receipts"] = [
        row for row in query_results["migration_receipts"] if row["migration_id"] != missing
    ]

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert f"migration_receipt_missing:{missing}" in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_on_orphan_count() -> None:
    query_results = _good_query_results()
    query_results["orphan_counts"][0]["artifact_manifest_orphans"] = 1

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert "orphan_count_nonzero:artifact_manifest_orphans" in receipt["summary"]["blockers"]


@pytest.mark.parametrize(
    "field",
    [
        "projection_finalize_receipt_orphans",
        "projection_job_orphans",
        "projection_artifact_orphans",
        "finalize_receipt_conflicts",
        "projection_guard_mismatches",
    ],
)
def test_restore_drill_fails_closed_on_projection_receipt_integrity_counts(
    field: str,
) -> None:
    query_results = _good_query_results()
    query_results["orphan_counts"][0][field] = 1

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert f"orphan_count_nonzero:{field}" in receipt["summary"]["blockers"]
    assert receipt["evidence"]["orphan_counts"][field] == 1


def test_restore_drill_fails_closed_when_noncommitted_artifacts_exist() -> None:
    query_results = _good_query_results()
    query_results["artifact_status_counts"] = [{"stored_count": 2, "failed_count": 1}]

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert (
        "artifact_manifest_status_invalid:noncommitted_artifacts:stored=2,failed=1"
        in receipt["summary"]["blockers"]
    )
    assert receipt["evidence"]["noncommitted_artifacts"] == {"stored": 2, "failed": 1}


@pytest.mark.parametrize(
    ("rows", "blocker"),
    [
        ([], "artifact_status_counts_missing"),
        ([{"stored_count": 0}], "artifact_status_counts_malformed"),
        ([{"stored_count": "0", "failed_count": True}], "artifact_status_counts_malformed"),
        (
            [{"stored_count": 0, "failed_count": 0}, {"stored_count": 0, "failed_count": 0}],
            "artifact_status_counts_malformed",
        ),
    ],
)
def test_restore_drill_fails_closed_without_complete_artifact_status_counts(
    rows: list[dict[str, Any]],
    blocker: str,
) -> None:
    query_results = _good_query_results()
    query_results["artifact_status_counts"] = rows

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert blocker in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_on_checksum_mismatch() -> None:
    receipt = _receipt(artifact_receipts={ARTIFACT_KEY: {"sha256": SHA_B, "bytes": 48}})

    assert receipt["status"] == "failed"
    assert f"artifact_sha256_mismatch:{ARTIFACT_KEY}" in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_on_failed_artifact() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"][0]["status"] = "failed"

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert f"artifact_manifest_status_invalid:{ARTIFACT_KEY}" in receipt["summary"][
        "blockers"
    ]


def test_restore_drill_fails_closed_on_stored_artifact() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"][0]["status"] = "stored"

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert f"artifact_manifest_status_invalid:{ARTIFACT_KEY}" in receipt["summary"][
        "blockers"
    ]


def test_artifact_key_ignores_uncommitted_manifest_rows() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"][0]["status"] = "stored"

    assert drill.selected_artifact_object_key(query_results) is None


def test_restore_drill_requires_namespaced_artifact_key() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"][0]["object_key"] = "imports/batch-1.ndjson"

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert (
        "artifact_manifest_object_key_invalid:imports/batch-1.ndjson"
        in receipt["summary"]["blockers"]
    )


def test_restore_drill_requires_content_addressed_artifact_key() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"][0]["object_key"] = (
        f"imports/v1/2026/08/02/{SHA_B}.json"
    )
    receipts = {f"imports/v1/2026/08/02/{SHA_B}.json": {"sha256": SHA_A, "bytes": 48}}

    receipt = _receipt(query_results=query_results, artifact_receipts=receipts)

    assert receipt["status"] == "failed"
    assert any(
        blocker.startswith("artifact_object_key_sha_mismatch:")
        for blocker in receipt["summary"]["blockers"]
    )


def test_restore_drill_fails_closed_on_backup_roundtrip_mismatch() -> None:
    backup = _good_backup_receipt()
    backup["downloaded"]["sha256"] = SHA_A

    receipt = _receipt(backup_receipt=backup)

    assert receipt["status"] == "failed"
    assert "backup_sha256_mismatch" in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_when_artifact_is_missing() -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"] = []

    receipt = _receipt(
        query_results=query_results,
        artifact_receipts={},
    )

    assert receipt["status"] == "failed"
    assert receipt["summary"]["artifact_coverage"] == "not_available"
    assert "artifact_manifest_missing" in receipt["summary"]["blockers"]


def test_restore_drill_fails_closed_on_invalid_public_snapshot_json() -> None:
    query_results = _good_query_results()
    query_results["public_snapshots"][0]["payload_json"] = "{invalid"

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert (
        "public_snapshot_json_invalid:news:featured:v1:page_size=20"
        in receipt["summary"]["blockers"]
    )


def test_restore_drill_fails_closed_on_missing_or_empty_row_counts() -> None:
    query_results = _good_query_results()
    query_results["row_counts"] = [
        row for row in query_results["row_counts"] if row["table"] != "targets"
    ]
    query_results["row_counts"][0]["row_count"] = 0

    receipt = _receipt(query_results=query_results)

    assert receipt["status"] == "failed"
    assert "row_count_missing:targets" in receipt["summary"]["blockers"]
    assert "row_count_empty:events" in receipt["summary"]["blockers"]


def test_object_receipt_hashes_file_without_body(tmp_path: Path) -> None:
    export = tmp_path / "export.ndjson"
    export.write_text(BODY, encoding="utf-8")

    receipt = drill.object_receipt(export)
    payload = {"object": receipt.__dict__}

    assert receipt.bytes == len(BODY.encode("utf-8"))
    assert receipt.sha256 == hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    assert BODY not in json.dumps(payload, ensure_ascii=False)
    assert str(export) not in json.dumps(payload, ensure_ascii=False)


def test_validate_cli_writes_failed_receipt_for_protected_database(tmp_path: Path) -> None:
    query_path = tmp_path / "queries.json"
    artifact_path = tmp_path / "artifacts.json"
    backup_path = tmp_path / "backup.json"
    output_path = tmp_path / "receipt.json"
    query_path.write_text(json.dumps(_good_query_results()), encoding="utf-8")
    artifact_path.write_text(json.dumps(_good_artifact_receipts()), encoding="utf-8")
    backup_path.write_text(json.dumps(_good_backup_receipt()), encoding="utf-8")
    continuity_path = tmp_path / "continuity.json"
    continuity_path.write_text(
        json.dumps({"status": "slo_7d_passed", "deployed_commit": COMMIT_A}),
        encoding="utf-8",
    )

    code = drill.main(
        [
            "validate",
            "--database",
            "ns-db",
            "--query-results",
            str(query_path),
            "--artifact-receipts",
            str(artifact_path),
            "--backup-receipt",
            str(backup_path),
            "--source-environment",
            "production",
            "--expected-commit",
            COMMIT_A,
            "--continuity-receipt",
            str(continuity_path),
            "--output",
            str(output_path),
        ]
    )

    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 2
    assert receipt["status"] == "failed"
    assert receipt["summary"]["blockers"] == ["protected_restore_database:ns-db"]


def test_validate_cli_success_with_json_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    query_results = copy.deepcopy(_good_query_results())
    artifact_receipts = copy.deepcopy(_good_artifact_receipts())
    query_path = tmp_path / "queries.json"
    artifact_path = tmp_path / "artifacts.json"
    backup_path = tmp_path / "backup.json"
    output_path = tmp_path / "receipt.json"
    query_path.write_text(json.dumps(query_results), encoding="utf-8")
    artifact_path.write_text(json.dumps(artifact_receipts), encoding="utf-8")
    backup_path.write_text(json.dumps(_good_backup_receipt()), encoding="utf-8")
    continuity_path = tmp_path / "continuity.json"
    continuity_path.write_text(
        json.dumps({"status": "slo_7d_passed", "deployed_commit": COMMIT_A}),
        encoding="utf-8",
    )

    code = drill.main(
        [
            "validate",
            "--database",
            "ns-db-restore-drill-20260802-3",
            "--query-results",
            str(query_path),
            "--artifact-receipts",
            str(artifact_path),
            "--backup-receipt",
            str(backup_path),
            "--source-environment",
            "production",
            "--expected-commit",
            COMMIT_A,
            "--continuity-receipt",
            str(continuity_path),
            "--output",
            str(output_path),
        ]
    )

    stdout = capsys.readouterr().out
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert receipt["status"] == "ok"
    assert json.loads(stdout)["status"] == "ok"


def test_validate_cli_fails_closed_when_artifact_evidence_is_missing(
    tmp_path: Path,
) -> None:
    query_results = _good_query_results()
    query_results["artifact_manifests"] = []
    query_path = tmp_path / "queries.json"
    artifact_path = tmp_path / "artifacts.json"
    backup_path = tmp_path / "backup.json"
    output_path = tmp_path / "receipt.json"
    query_path.write_text(json.dumps(query_results), encoding="utf-8")
    artifact_path.write_text("{}", encoding="utf-8")
    backup_path.write_text(json.dumps(_good_backup_receipt()), encoding="utf-8")
    continuity_path = tmp_path / "continuity.json"
    continuity_path.write_text(
        json.dumps({"status": "slo_7d_passed", "deployed_commit": COMMIT_A}),
        encoding="utf-8",
    )

    code = drill.main(
        [
            "validate",
            "--database",
            "ns-db-restore-drill-20260802-5",
            "--query-results",
            str(query_path),
            "--artifact-receipts",
            str(artifact_path),
            "--backup-receipt",
            str(backup_path),
            "--source-environment",
            "production",
            "--expected-commit",
            COMMIT_A,
            "--continuity-receipt",
            str(continuity_path),
            "--output",
            str(output_path),
        ]
    )

    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 2
    assert receipt["status"] == "failed"
    assert "artifact_manifest_missing" in receipt["summary"]["blockers"]


@pytest.mark.parametrize(
    ("content", "blocker"),
    [
        ("", "continuity_receipt_missing"),
        ("not json", "continuity_receipt_malformed"),
        ("[]", "continuity_receipt_malformed"),
        (
            json.dumps({"status": "canary_72h_passed", "deployed_commit": COMMIT_A}),
            "continuity_slo_7d_not_passed",
        ),
        (
            json.dumps({"status": "slo_7d_passed", "deployed_commit": COMMIT_B}),
            "continuity_commit_mismatch",
        ),
    ],
)
def test_validate_cli_writes_concrete_continuity_blockers(
    tmp_path: Path,
    content: str,
    blocker: str,
) -> None:
    query_path = tmp_path / "queries.json"
    artifact_path = tmp_path / "artifacts.json"
    backup_path = tmp_path / "backup.json"
    output_path = tmp_path / "receipt.json"
    continuity_path = tmp_path / "continuity.json"
    query_path.write_text(json.dumps(_good_query_results()), encoding="utf-8")
    artifact_path.write_text(json.dumps(_good_artifact_receipts()), encoding="utf-8")
    backup_path.write_text(json.dumps(_good_backup_receipt()), encoding="utf-8")
    continuity_path.write_text(content, encoding="utf-8")

    code = drill.main(
        [
            "validate",
            "--database",
            "ns-db-restore-drill-20260802-7",
            "--query-results",
            str(query_path),
            "--artifact-receipts",
            str(artifact_path),
            "--backup-receipt",
            str(backup_path),
            "--source-environment",
            "production",
            "--expected-commit",
            COMMIT_A,
            "--continuity-receipt",
            str(continuity_path),
            "--output",
            str(output_path),
        ]
    )

    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 2
    assert receipt["status"] == "failed"
    assert blocker in receipt["summary"]["blockers"]


def test_validate_cli_rejects_missing_artifact_bypass_option(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    query_path = tmp_path / "queries.json"
    artifact_path = tmp_path / "artifacts.json"
    backup_path = tmp_path / "backup.json"
    query_path.write_text(json.dumps(_good_query_results()), encoding="utf-8")
    artifact_path.write_text(json.dumps(_good_artifact_receipts()), encoding="utf-8")
    backup_path.write_text(json.dumps(_good_backup_receipt()), encoding="utf-8")
    continuity_path = tmp_path / "continuity.json"
    continuity_path.write_text(
        json.dumps({"status": "slo_7d_passed", "deployed_commit": COMMIT_A}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        drill.main(
            [
                "validate",
                "--database",
                "ns-db-restore-drill-20260802-6",
                "--query-results",
                str(query_path),
                "--artifact-receipts",
                str(artifact_path),
                "--backup-receipt",
                str(backup_path),
                "--source-environment",
                "production",
                "--expected-commit",
                COMMIT_A,
                "--continuity-receipt",
                str(continuity_path),
                "--allow-missing-artifact",
            ]
        )

    assert exc_info.value.code == 2
    assert "allow-missing-artifact" in capsys.readouterr().err


def test_run_wrangler_d1_query_propagates_runner_errors_without_shell() -> None:
    def failing_runner(args: list[str]) -> str:
        assert args[0:3] == ["wrangler", "d1", "execute"]
        raise subprocess.CalledProcessError(1, args, stderr="nope")

    with pytest.raises(subprocess.CalledProcessError):
        drill.run_wrangler_d1_query(
            wrangler="wrangler",
            database="ns-db-restore-drill-20260802-4",
            sql="SELECT 1",
            remote=True,
            runner=failing_runner,
        )
