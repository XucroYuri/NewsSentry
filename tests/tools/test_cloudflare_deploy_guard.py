from __future__ import annotations

import json

import pytest
from tools.cloudflare_deploy_guard import (
    GuardConfig,
    ReceiptError,
    build_deploy_receipt,
    run_preflight,
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


def _json(value: object) -> str:
    return json.dumps(value)


def test_preflight_blocks_missing_queue_without_blind_create() -> None:
    runner = FakeRunner(
        {
            ("wrangler", "queues", "list", "--json"): _json(
                [{"queue_name": "news-sentry-jobs"}]
            ),
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
                "SELECT name FROM d1_migrations ORDER BY name",
                "--json",
            ): _json([{"results": [{"name": "20260801_phase1_job_runtime.sql"}]}]),
        }
    )

    receipt = run_preflight(
        GuardConfig(expected_migrations=("20260802_phase2_import_staging.sql",)),
        runner=runner,
    )

    assert receipt["status"] == "blocked"
    assert "missing_queue:news-sentry-jobs-dlq" in receipt["blockers"]
    assert "consumer_missing:news-sentry-jobs" in receipt["blockers"]
    assert "missing_applied_migration:20260802_phase2_import_staging.sql" in receipt["blockers"]
    assert not any(call[:3] == ("wrangler", "queues", "create") for call in runner.calls)


def test_preflight_apply_lists_before_creating_missing_queue() -> None:
    runner = FakeRunner(
        {
            ("wrangler", "queues", "list", "--json"): _json([]),
            ("wrangler", "queues", "create", "news-sentry-jobs"): "created",
            ("wrangler", "queues", "create", "news-sentry-jobs-dlq"): "created",
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
                "SELECT name FROM d1_migrations ORDER BY name",
                "--json",
            ): _json(
                [
                    {
                        "results": [
                            {"name": "20260801_phase1_job_runtime.sql"},
                            {"name": "20260802_phase2_import_staging.sql"},
                        ]
                    }
                ]
            ),
        }
    )

    receipt = run_preflight(
        GuardConfig(
            expected_migrations=("20260802_phase2_import_staging.sql",),
            apply=True,
        ),
        runner=runner,
    )

    assert receipt["status"] == "ok"
    assert runner.calls[0] == ("wrangler", "queues", "list", "--json")
    assert ("wrangler", "queues", "create", "news-sentry-jobs") in runner.calls
    assert ("wrangler", "queues", "create", "news-sentry-jobs-dlq") in runner.calls


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
        applied_migrations=("20260802_phase2_import_staging.sql",),
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
        applied_migrations=("20260802_phase2_import_staging.sql",),
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
            applied_migrations=(),
            queue_receipt={"status": "ok"},
        )
