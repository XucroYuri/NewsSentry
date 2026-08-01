from __future__ import annotations

import json
import subprocess

import pytest
from tools.cloudflare_deploy_guard import (
    GuardConfig,
    ReceiptError,
    build_deploy_receipt,
    record_runtime_receipts,
    run_preflight,
)

EXPECTED_RUNTIME_RECEIPTS = (
    "20260801_phase0_data_quarantine",
    "20260801_phase1_job_runtime",
    "20260802_phase2_import_staging",
    "20260802_phase2_dlq_replay_receipts",
)
RUNTIME_SCHEMA_TABLE_QUERY = (
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
    "('import_staged_events','import_batch_finalize_receipts',"
    "'dlq_replay_receipts','dlq_consumption_receipts')"
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str]) -> str:
        key = tuple(args)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"unexpected command: {' '.join(args)}")
        return self.responses[key]


class FakeTransport:
    def __init__(self, responses: dict[tuple[str, str], tuple[int, object]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, object | None]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: object | None,
    ) -> tuple[int, str]:
        del headers
        self.calls.append((method, url, body))
        status, payload = self.responses[(method, url)]
        return status, json.dumps(payload)


def _json(value: object) -> str:
    return json.dumps(value)


def _queue_url(account_id: str = "acct-1") -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/queues"


def _runtime_receipts(rows: list[dict[str, str]]) -> str:
    return _json([{"results": rows}])


def _schema_ok_responses() -> dict[tuple[str, ...], str]:
    return {
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(quarantined_events)",
            "--json",
        ): _json([{"results": [{"name": "quarantine_id"}]}]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(import_batches)",
            "--json",
        ): _json(
            [
                {
                    "results": [
                        {"name": "expected_chunks"},
                        {"name": "committed_chunks"},
                        {"name": "payload_bytes"},
                        {"name": "output_watermark"},
                    ]
                }
            ]
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            RUNTIME_SCHEMA_TABLE_QUERY,
            "--json",
        ): _json(
            [
                {
                    "results": [
                        {"name": "import_staged_events"},
                        {"name": "import_batch_finalize_receipts"},
                        {"name": "dlq_replay_receipts"},
                        {"name": "dlq_consumption_receipts"},
                    ]
                }
            ]
        ),
    }


def test_preflight_blocks_missing_queue_without_blind_create() -> None:
    runner = FakeRunner(
        {
            (
                "wrangler",
                "queues",
                "consumer",
                "worker",
                "list",
                "news-sentry-jobs",
                "--json",
            ): _json([]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id",
                "--json",
            ): _runtime_receipts([{"migration_id": "20260801_phase1_job_runtime"}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "PRAGMA table_info(quarantined_events)",
                "--json",
            ): _json([{"results": [{"name": "quarantine_id"}]}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "PRAGMA table_info(import_batches)",
                "--json",
            ): _json([{"results": [{"name": "expected_chunks"}]}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                RUNTIME_SCHEMA_TABLE_QUERY,
                "--json",
            ): _json([{"results": [{"name": "import_staged_events"}]}]),
        }
    )
    transport = FakeTransport(
        {
            ("GET", _queue_url()): (
                200,
                {"success": True, "result": [{"queue_name": "news-sentry-jobs"}]},
            )
        }
    )

    receipt = run_preflight(
        GuardConfig(
            account_id="acct-1",
            api_key="key",
            api_email="ops@example.test",
            expected_migration_receipts=("20260802_phase2_import_staging",),
        ),
        runner=runner,
        transport=transport,
    )

    assert receipt["status"] == "blocked"
    assert "missing_queue:news-sentry-jobs-dlq" in receipt["blockers"]
    assert "consumer_missing:news-sentry-jobs" in receipt["blockers"]
    assert "missing_runtime_migration_receipt:20260802_phase2_import_staging" in receipt["blockers"]
    assert "schema_table_missing:import_batch_finalize_receipts" in receipt["blockers"]
    assert ("wrangler", "queues", "list", "--json") not in runner.calls
    assert not any(call[:3] == ("wrangler", "queues", "create") for call in runner.calls)


def test_preflight_apply_uses_api_list_before_creating_missing_queue() -> None:
    runner = FakeRunner(
        {
            (
                "wrangler",
                "queues",
                "consumer",
                "worker",
                "list",
                "news-sentry-jobs",
                "--json",
            ): _json(
                [
                    {
                        "service": "news-sentry-api",
                        "queue_name": "news-sentry-jobs",
                        "settings": {
                            "max_batch_size": 5,
                            "max_batch_timeout": 5,
                            "max_retries": 3,
                            "max_concurrency": 1,
                        },
                    }
                ]
            ),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id",
                "--json",
            ): _json(
                [
                    {
                        "results": [
                            {"migration_id": "20260801_phase0_data_quarantine"},
                            {"migration_id": "20260801_phase1_job_runtime"},
                            {"migration_id": "20260802_phase2_import_staging"},
                            {"migration_id": "20260802_phase2_dlq_replay_receipts"},
                        ]
                    }
                ]
            ),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "PRAGMA table_info(quarantined_events)",
                "--json",
            ): _json([{"results": [{"name": "quarantine_id"}]}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "PRAGMA table_info(import_batches)",
                "--json",
            ): _json(
                [
                    {
                        "results": [
                            {"name": "expected_chunks"},
                            {"name": "committed_chunks"},
                            {"name": "payload_bytes"},
                            {"name": "output_watermark"},
                        ]
                    }
                ]
            ),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                RUNTIME_SCHEMA_TABLE_QUERY,
                "--json",
            ): _json(
                [
                    {
                        "results": [
                            {"name": "import_staged_events"},
                            {"name": "import_batch_finalize_receipts"},
                            {"name": "dlq_replay_receipts"},
                            {"name": "dlq_consumption_receipts"},
                        ]
                    }
                ]
            ),
        }
    )
    transport = FakeTransport(
        {
            ("GET", _queue_url()): (200, {"success": True, "result": []}),
            ("POST", _queue_url()): (200, {"success": True, "result": {"queue_name": "created"}}),
        }
    )

    receipt = run_preflight(
        GuardConfig(
            account_id="acct-1",
            api_token="token-1",  # noqa: S106 - fake Cloudflare API token fixture.
            apply=True,
        ),
        runner=runner,
        transport=transport,
    )

    assert receipt["status"] == "ok"
    assert transport.calls[0][0:2] == ("GET", _queue_url())
    assert ("POST", _queue_url(), {"queue_name": "news-sentry-jobs"}) in transport.calls
    assert ("POST", _queue_url(), {"queue_name": "news-sentry-jobs-dlq"}) in transport.calls
    assert not any(call[:3] == ("wrangler", "queues", "create") for call in runner.calls)


def test_preflight_returns_structured_blocked_receipt_on_command_failure() -> None:
    def failing_runner(args: list[str]) -> str:
        raise subprocess.CalledProcessError(1, args, stderr="unsupported flag")

    transport = FakeTransport(
        {
            ("GET", _queue_url()): (
                200,
                {
                    "success": True,
                    "result": [
                        {"queue_name": "news-sentry-jobs"},
                        {"queue_name": "news-sentry-jobs-dlq"},
                    ],
                },
            )
        }
    )

    receipt = run_preflight(
        GuardConfig(account_id="acct-1", api_token="token-1"),  # noqa: S106
        runner=failing_runner,
        transport=transport,
    )

    assert receipt["status"] == "blocked"
    assert any(str(blocker).startswith("command_failed:") for blocker in receipt["blockers"])
    assert "unsupported flag" in json.dumps(receipt)


def test_record_runtime_receipts_verifies_schema_before_project_receipt() -> None:
    insert_prefix = (
        "wrangler",
        "d1",
        "execute",
        "ns-db",
        "--remote",
        "--command",
    )
    expected_insert = (
        "INSERT OR IGNORE INTO runtime_migration_receipts (migration_id, details_json) "
        "VALUES ('20260801_phase0_data_quarantine', "
        "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
        "('20260801_phase1_job_runtime', "
        "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
        "('20260802_phase2_import_staging', "
        "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
        "('20260802_phase2_dlq_replay_receipts', "
        "'{\"recorded_by\":\"cloudflare_deploy_guard\"}')"
    )
    runner = FakeRunner(
        {
            **_schema_ok_responses(),
            (
                *insert_prefix,
                expected_insert,
                "--json",
            ): _json([{"results": []}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id",
                "--json",
            ): _runtime_receipts(
                [{"migration_id": receipt} for receipt in EXPECTED_RUNTIME_RECEIPTS]
            ),
        }
    )

    receipt = record_runtime_receipts(GuardConfig(), runner=runner)

    assert receipt["status"] == "ok"
    assert receipt["runtime_migration_receipts"] == sorted(EXPECTED_RUNTIME_RECEIPTS)
    assert runner.calls[0][6] == "PRAGMA table_info(quarantined_events)"
    assert "INSERT OR IGNORE INTO runtime_migration_receipts" in runner.calls[3][6]


def test_record_runtime_receipts_blocks_before_insert_when_schema_not_equivalent() -> None:
    runner = FakeRunner(
        {
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "PRAGMA table_info(quarantined_events)",
                "--json",
            ): _json([{"results": []}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "PRAGMA table_info(import_batches)",
                "--json",
            ): _json([{"results": []}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                RUNTIME_SCHEMA_TABLE_QUERY,
                "--json",
            ): _json([{"results": []}]),
            (
                "wrangler",
                "d1",
                "execute",
                "ns-db",
                "--remote",
                "--command",
                "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id",
                "--json",
            ): _runtime_receipts([]),
        }
    )

    receipt = record_runtime_receipts(GuardConfig(), runner=runner)

    assert receipt["status"] == "blocked"
    assert "schema_column_missing:quarantined_events.quarantine_id" in receipt["blockers"]
    assert not any(
        "INSERT OR IGNORE INTO runtime_migration_receipts" in call[6]
        for call in runner.calls
    )


def test_build_deploy_receipt_requires_matching_commit_version_and_health_mode() -> None:
    receipt = build_deploy_receipt(
        expected_commit="abc123",
        expected_scheduler_mode="shadow",
        version_json={"id": "version-1", "metadata": {"source": "unit"}},
        deployment_json={"id": "deployment-1", "version_id": "version-1", "status": "active"},
        health_json={
            "status": "ok",
            "deployment": {
                "commit": "abc123",
                "worker_version": "version-1",
                "scheduler_mode": "shadow",
                "worker_native_collect_enabled": False,
            },
            "collection": {"authoritative": False},
            "queue": {"configured": True, "dlq": {"configured": True}},
        },
        applied_migration_receipts=EXPECTED_RUNTIME_RECEIPTS,
        queue_receipt={"status": "ok"},
    )

    assert receipt["status"] == "ok"
    assert receipt["commit"] == "abc123"
    assert receipt["worker_version"] == "version-1"
    assert receipt["health_mode"] == "shadow"


def test_build_deploy_receipt_accepts_weighted_deployment_versions() -> None:
    receipt = build_deploy_receipt(
        expected_commit="abc123",
        expected_scheduler_mode="shadow",
        version_json={"id": "version-1"},
        deployment_json={
            "id": "deployment-1",
            "versions": [{"version_id": "version-1", "percentage": 100}],
        },
        health_json={
            "status": "ok",
            "deployment": {
                "commit": "abc123",
                "worker_version": "version-1",
                "scheduler_mode": "shadow",
                "worker_native_collect_enabled": False,
            },
            "collection": {"authoritative": False},
            "queue": {"configured": True, "dlq": {"configured": True}},
        },
        applied_migration_receipts=EXPECTED_RUNTIME_RECEIPTS,
        queue_receipt={"status": "ok"},
    )

    assert receipt["deployment_id"] == "deployment-1"


def test_build_deploy_receipt_rejects_dry_run_style_incomplete_evidence() -> None:
    with pytest.raises(ReceiptError):
        build_deploy_receipt(
            expected_commit="abc123",
            expected_scheduler_mode="shadow",
            version_json={},
            deployment_json={},
            health_json={"status": "ok"},
            applied_migration_receipts=(),
            queue_receipt={"status": "ok"},
        )
