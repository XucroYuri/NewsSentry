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
    "20260802_phase3_durable_artifacts",
)
RUNTIME_SCHEMA_TABLE_QUERY = (
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
    "('import_staged_events','import_batch_finalize_receipts',"
    "'dlq_replay_receipts','dlq_consumption_receipts','artifact_manifests')"
)
REQUIRED_RUNTIME_INDEX_QUERY = (
    "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
    "('idx_jobs_status_scheduled','idx_job_outbox_dispatch',"
    "'idx_source_runtime_due','idx_import_staged_events_batch_chunk',"
    "'idx_dlq_replay_receipts_original','idx_dlq_consumption_receipts_consumed',"
    "'idx_artifact_manifests_status_created','idx_artifact_manifests_job')"
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
    def __init__(
        self,
        responses: dict[
            tuple[str, str],
            tuple[int, object] | list[tuple[int, object]],
        ],
    ) -> None:
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
        response = self.responses[(method, url)]
        if isinstance(response, list):
            status, payload = response.pop(0)
        else:
            status, payload = response
        return status, json.dumps(payload)


def _json(value: object) -> str:
    return json.dumps(value)


def _queue_url(account_id: str = "acct-1") -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/queues"


def _queue_page_url(account_id: str = "acct-1", page: int = 1) -> str:
    return f"{_queue_url(account_id)}?page={page}"


def _runtime_receipts(rows: list[dict[str, str]]) -> str:
    return _json([{"results": rows}])


def _table_info(columns: list[str], pk: list[str] | None = None) -> str:
    pk = pk or []
    return _json(
        [
            {
                "results": [
                    {"name": column, "pk": pk.index(column) + 1 if column in pk else 0}
                    for column in columns
                ]
            }
        ]
    )


def _index_list(indexes: list[tuple[str, bool]]) -> str:
    return _json(
        [
            {
                "results": [
                    {"name": name, "unique": 1 if unique else 0}
                    for name, unique in indexes
                ]
            }
        ]
    )


def _index_info(columns: list[str]) -> str:
    return _json([{"results": [{"name": column} for column in columns]}])


def _schema_ok_responses() -> dict[tuple[str, ...], str]:
    return {
        (
            "wrangler",
            "r2",
            "bucket",
            "list",
            "--json",
        ): _json([{"name": "news-sentry-artifacts"}]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(quarantined_events)",
            "--json",
        ): _table_info(
            [
                "quarantine_id",
                "target_id",
                "source_id",
                "reason_code",
                "payload_json",
                "created_at",
                "reviewed_at",
            ],
            pk=["quarantine_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(jobs)",
            "--json",
        ): _table_info(
            [
                "job_id",
                "idempotency_key",
                "replay_of_job_id",
                "job_type",
                "target_id",
                "source_id",
                "capability",
                "scheduled_for",
                "scheduled_window",
                "status",
                "attempt_count",
                "max_attempts",
                "lease_token",
                "lease_owner",
                "lease_until",
                "fencing_version",
                "input_cursor",
                "output_watermark",
                "last_error_code",
                "last_error_message",
                "created_at",
                "updated_at",
                "finished_at",
            ],
            pk=["job_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(jobs)",
            "--json",
        ): _index_list([("sqlite_autoindex_jobs_2", True)]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_jobs_2)",
            "--json",
        ): _index_info(["idempotency_key"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(job_outbox)",
            "--json",
        ): _table_info(
            [
                "outbox_id",
                "job_id",
                "status",
                "dispatch_attempts",
                "next_dispatch_at",
                "dispatched_at",
                "created_at",
                "updated_at",
            ],
            pk=["outbox_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(job_outbox)",
            "--json",
        ): _index_list([("sqlite_autoindex_job_outbox_2", True)]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_job_outbox_2)",
            "--json",
        ): _index_info(["job_id"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(source_runtime_state)",
            "--json",
        ): _table_info(
            [
                "target_id",
                "source_id",
                "tier",
                "capability",
                "state",
                "next_due_at",
                "last_attempt_at",
                "last_success_at",
                "consecutive_failures",
                "rolling_success_rate",
                "backoff_until",
                "cursor",
                "etag",
                "last_modified",
                "quarantine_count",
                "config_version",
                "updated_at",
            ],
            pk=["target_id", "source_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(import_batches)",
            "--json",
        ): _table_info(
            [
                "batch_id",
                "job_id",
                "status",
                "received_count",
                "valid_count",
                "quarantined_count",
                "imported_count",
                "updated_count",
                "checksum",
                "started_at",
                "committed_at",
                "error_code",
                "expected_chunks",
                "committed_chunks",
                "payload_bytes",
                "output_watermark",
                "error_message",
            ],
            pk=["batch_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(import_batches)",
            "--json",
        ): _index_list([("sqlite_autoindex_import_batches_2", True)]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_import_batches_2)",
            "--json",
        ): _index_info(["job_id"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(import_batch_chunks)",
            "--json",
        ): _table_info(
            [
                "batch_id",
                "chunk_no",
                "checksum",
                "status",
                "statement_count",
                "payload_bytes",
                "committed_at",
                "error_message",
            ],
            pk=["batch_id", "chunk_no"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(runtime_migration_receipts)",
            "--json",
        ): _table_info(
            ["migration_id", "applied_at", "deploy_commit", "details_json"],
            pk=["migration_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(import_staged_events)",
            "--json",
        ): _table_info(
            [
                "batch_id",
                "chunk_no",
                "event_id",
                "target_id",
                "source_id",
                "event_fingerprint",
                "payload_json",
                "staged_at",
            ],
            pk=["batch_id", "event_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(import_batch_finalize_receipts)",
            "--json",
        ): _table_info(
            [
                "batch_id",
                "job_id",
                "target_id",
                "source_id",
                "batch_checksum",
                "lease_token",
                "fencing_version",
                "output_watermark",
                "finalized_at",
                "batch_guard",
                "job_guard",
                "source_guard",
            ],
            pk=["batch_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(dlq_replay_receipts)",
            "--json",
        ): _table_info(
            [
                "receipt_id",
                "original_job_id",
                "new_job_id",
                "operator_id",
                "reason",
                "requested_version",
                "worker_version",
                "deploy_commit",
                "created_at",
                "details_json",
            ],
            pk=["receipt_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(dlq_replay_receipts)",
            "--json",
        ): _index_list([("sqlite_autoindex_dlq_replay_receipts_2", True)]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_dlq_replay_receipts_2)",
            "--json",
        ): _index_info(["new_job_id"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(dlq_consumption_receipts)",
            "--json",
        ): _table_info(
            [
                "receipt_id",
                "job_id",
                "queue_name",
                "message_body_json",
                "worker_version",
                "consumed_at",
            ],
            pk=["receipt_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(dlq_consumption_receipts)",
            "--json",
        ): _index_list([("sqlite_autoindex_dlq_consumption_receipts_2", True)]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_dlq_consumption_receipts_2)",
            "--json",
        ): _index_info(["job_id", "queue_name"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(artifact_manifests)",
            "--json",
        ): _table_info(
            [
                "artifact_id",
                "batch_id",
                "job_id",
                "object_key",
                "sha256",
                "payload_bytes",
                "content_type",
                "r2_etag",
                "r2_version",
                "status",
                "created_at",
                "finalized_at",
                "error_code",
                "error_message",
                "details_json",
            ],
            pk=["artifact_id"],
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(artifact_manifests)",
            "--json",
        ): _index_list(
            [
                ("sqlite_autoindex_artifact_manifests_2", True),
                ("sqlite_autoindex_artifact_manifests_3", True),
            ]
        ),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_artifact_manifests_2)",
            "--json",
        ): _index_info(["batch_id"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_info(sqlite_autoindex_artifact_manifests_3)",
            "--json",
        ): _index_info(["object_key"]),
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            REQUIRED_RUNTIME_INDEX_QUERY,
            "--json",
        ): _json(
            [
                {
                    "results": [
                        {"name": "idx_jobs_status_scheduled"},
                        {"name": "idx_job_outbox_dispatch"},
                        {"name": "idx_source_runtime_due"},
                        {"name": "idx_import_staged_events_batch_chunk"},
                        {"name": "idx_dlq_replay_receipts_original"},
                        {"name": "idx_dlq_consumption_receipts_consumed"},
                        {"name": "idx_artifact_manifests_status_created"},
                        {"name": "idx_artifact_manifests_job"},
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
                        {"name": "artifact_manifests"},
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
            ("GET", _queue_page_url(page=1)): (
                200,
                {
                    "success": True,
                    "result": [{"queue_name": "news-sentry-jobs"}],
                    "result_info": {"page": 1, "total_pages": 1},
                },
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
                            {"migration_id": "20260802_phase3_durable_artifacts"},
                        ]
                    }
                ]
            ),
            **_schema_ok_responses(),
        }
    )
    transport = FakeTransport(
        {
            ("GET", _queue_page_url(page=1)): [
                (
                    200,
                    {
                        "success": True,
                        "result": [],
                        "result_info": {"page": 1, "total_pages": 1},
                    },
                ),
                (
                    200,
                    {
                        "success": True,
                        "result": [{"queue_name": "news-sentry-jobs"}],
                        "result_info": {"page": 1, "total_pages": 1},
                    },
                ),
                (
                    200,
                    {
                        "success": True,
                        "result": [
                            {"queue_name": "news-sentry-jobs"},
                            {"queue_name": "news-sentry-jobs-dlq"},
                        ],
                        "result_info": {"page": 1, "total_pages": 1},
                    },
                ),
            ],
            ("POST", _queue_url()): [
                (
                    200,
                    {"success": True, "result": {"queue_name": "news-sentry-jobs"}},
                ),
                (
                    200,
                    {"success": True, "result": {"queue_name": "news-sentry-jobs-dlq"}},
                ),
            ],
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
    assert transport.calls[0][0:2] == ("GET", _queue_page_url(page=1))
    assert ("POST", _queue_url(), {"queue_name": "news-sentry-jobs"}) in transport.calls
    assert ("POST", _queue_url(), {"queue_name": "news-sentry-jobs-dlq"}) in transport.calls
    assert not any(call[:3] == ("wrangler", "queues", "create") for call in runner.calls)


def test_preflight_uses_paginated_queue_rest_truth() -> None:
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
            ): _runtime_receipts(
                [{"migration_id": receipt} for receipt in EXPECTED_RUNTIME_RECEIPTS]
            ),
            **_schema_ok_responses(),
        }
    )
    transport = FakeTransport(
        {
            ("GET", _queue_page_url(page=1)): (
                200,
                {
                    "success": True,
                    "result": [{"queue_name": "some-other-queue"}],
                    "result_info": {"page": 1, "total_pages": 2},
                },
            ),
            ("GET", _queue_page_url(page=2)): (
                200,
                {
                    "success": True,
                    "result": [
                        {"queue_name": "news-sentry-jobs"},
                        {"queue_name": "news-sentry-jobs-dlq"},
                    ],
                    "result_info": {"page": 2, "total_pages": 2},
                },
            ),
        }
    )

    receipt = run_preflight(
        GuardConfig(account_id="acct-1", api_token="token-1"),  # noqa: S106
        runner=runner,
        transport=transport,
    )

    assert receipt["status"] == "ok"
    assert ("GET", _queue_page_url(page=1), None) in transport.calls
    assert ("GET", _queue_page_url(page=2), None) in transport.calls


def _queue_ok_runner() -> FakeRunner:
    return FakeRunner(
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
            ): _runtime_receipts(
                [{"migration_id": receipt} for receipt in EXPECTED_RUNTIME_RECEIPTS]
            ),
            **_schema_ok_responses(),
        }
    )


@pytest.mark.parametrize(
    ("payload", "expected_blocker"),
    [
        (
            {
                "success": True,
                "result": [
                    {"queue_name": "news-sentry-jobs"},
                    {"queue_name": "news-sentry-jobs-dlq"},
                ],
            },
            "queue_list_pagination_missing",
        ),
        (
            {
                "success": True,
                "result": [
                    {"queue_name": "news-sentry-jobs"},
                    {"queue_name": "news-sentry-jobs-dlq"},
                ],
                "result_info": "page-one",
            },
            "queue_list_pagination_invalid",
        ),
        (
            {
                "success": True,
                "result": [
                    {"queue_name": "news-sentry-jobs"},
                    {"queue_name": "news-sentry-jobs-dlq"},
                ],
                "result_info": {"page": "x", "total_pages": 1},
            },
            "queue_list_pagination_invalid",
        ),
        (
            {
                "success": True,
                "result": [
                    {"queue_name": "news-sentry-jobs"},
                    {"queue_name": "news-sentry-jobs-dlq"},
                ],
                "result_info": {"page": 0, "total_pages": 1},
            },
            "queue_list_pagination_invalid",
        ),
        (
            {
                "success": True,
                "result": [
                    {"queue_name": "news-sentry-jobs"},
                    {"queue_name": "news-sentry-jobs-dlq"},
                ],
                "result_info": {"page": 2, "total_pages": 2},
            },
            "queue_list_pagination_page_mismatch:expected=1:actual=2",
        ),
    ],
)
def test_preflight_blocks_malformed_queue_list_pagination(
    payload: object,
    expected_blocker: str,
) -> None:
    transport = FakeTransport({("GET", _queue_page_url(page=1)): (200, payload)})

    receipt = run_preflight(
        GuardConfig(account_id="acct-1", api_token="token-1"),  # noqa: S106
        runner=_queue_ok_runner(),
        transport=transport,
    )

    assert receipt["status"] == "blocked"
    assert expected_blocker in receipt["blockers"]
    assert receipt["queues"] == []


def test_preflight_blocks_queue_list_total_pages_drift() -> None:
    transport = FakeTransport(
        {
            ("GET", _queue_page_url(page=1)): (
                200,
                {
                    "success": True,
                    "result": [{"queue_name": "news-sentry-jobs"}],
                    "result_info": {"page": 1, "total_pages": 2},
                },
            ),
            ("GET", _queue_page_url(page=2)): (
                200,
                {
                    "success": True,
                    "result": [{"queue_name": "news-sentry-jobs-dlq"}],
                    "result_info": {"page": 2, "total_pages": 3},
                },
            ),
        }
    )

    receipt = run_preflight(
        GuardConfig(account_id="acct-1", api_token="token-1"),  # noqa: S106
        runner=_queue_ok_runner(),
        transport=transport,
    )

    assert receipt["status"] == "blocked"
    assert "queue_list_pagination_total_pages_drift:expected=2:actual=3" in receipt["blockers"]
    assert receipt["queues"] == []


def test_preflight_apply_blocks_wrong_create_response_without_local_queue_truth() -> None:
    runner = FakeRunner({**_schema_ok_responses()})
    transport = FakeTransport(
        {
            ("GET", _queue_page_url(page=1)): (
                200,
                {"success": True, "result": [], "result_info": {"page": 1, "total_pages": 1}},
            ),
            ("POST", _queue_url()): (
                200,
                {"success": True, "result": {"queue_name": "created"}},
            ),
        }
    )

    receipt = run_preflight(
        GuardConfig(account_id="acct-1", api_token="token-1", apply=True),  # noqa: S106
        runner=runner,
        transport=transport,
    )

    assert receipt["status"] == "blocked"
    assert "queue_create_response_mismatch:news-sentry-jobs" in receipt["blockers"]
    assert "news-sentry-jobs" not in receipt["queues"]


def test_preflight_apply_blocks_when_created_queue_revalidation_misses() -> None:
    runner = FakeRunner({**_schema_ok_responses()})
    transport = FakeTransport(
        {
            ("GET", _queue_page_url(page=1)): [
                (
                    200,
                    {"success": True, "result": [], "result_info": {"page": 1, "total_pages": 1}},
                ),
                (
                    200,
                    {"success": True, "result": [], "result_info": {"page": 1, "total_pages": 1}},
                ),
            ],
            ("POST", _queue_url()): (
                200,
                {"success": True, "result": {"queue_name": "news-sentry-jobs"}},
            ),
        }
    )

    receipt = run_preflight(
        GuardConfig(
            account_id="acct-1",
            api_token="token-1",  # noqa: S106
            apply=True,
            expected_migration_receipts=(),
        ),
        runner=runner,
        transport=transport,
    )

    assert receipt["status"] == "blocked"
    assert "queue_revalidation_missing:news-sentry-jobs" in receipt["blockers"]
    assert "news-sentry-jobs" not in receipt["queues"]


def test_preflight_returns_structured_blocked_receipt_on_command_failure() -> None:
    def failing_runner(args: list[str]) -> str:
        raise subprocess.CalledProcessError(1, args, stderr="unsupported flag")

    transport = FakeTransport(
        {
            ("GET", _queue_page_url(page=1)): (
                200,
                {
                    "success": True,
                    "result": [
                        {"queue_name": "news-sentry-jobs"},
                        {"queue_name": "news-sentry-jobs-dlq"},
                    ],
                    "result_info": {"page": 1, "total_pages": 1},
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
        "'{\"recorded_by\":\"cloudflare_deploy_guard\"}'), "
        "('20260802_phase3_durable_artifacts', "
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
    assert any(
        "INSERT OR IGNORE INTO runtime_migration_receipts" in call[6]
        for call in runner.calls
    )


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


def test_record_runtime_receipts_blocks_existing_dlq_tables_with_missing_columns() -> None:
    responses = _schema_ok_responses()
    responses[
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA table_info(dlq_replay_receipts)",
            "--json",
        )
    ] = _table_info(["receipt_id"], pk=["receipt_id"])
    runner = FakeRunner(
        {
            **responses,
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
    assert (
        "schema_column_missing:20260802_phase2_dlq_replay_receipts:"
        "dlq_replay_receipts.operator_id"
        in receipt["blockers"]
    )
    assert not any(
        "INSERT OR IGNORE INTO runtime_migration_receipts" in call[6]
        for call in runner.calls
    )


def test_record_runtime_receipts_blocks_missing_phase1_unique_constraint() -> None:
    responses = _schema_ok_responses()
    responses[
        (
            "wrangler",
            "d1",
            "execute",
            "ns-db",
            "--remote",
            "--command",
            "PRAGMA index_list(jobs)",
            "--json",
        )
    ] = _index_list([])
    runner = FakeRunner(
        {
            **responses,
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
    assert (
        "schema_unique_missing:20260801_phase1_job_runtime:jobs(idempotency_key)"
        in receipt["blockers"]
    )
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
