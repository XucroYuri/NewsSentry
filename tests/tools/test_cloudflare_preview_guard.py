from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS

from tools import cloudflare_preview_guard as guard

ROOT = Path(__file__).resolve().parents[2]


def test_select_preview_d1_requires_exact_unique_database() -> None:
    payload = {
        "result": [
            {"uuid": "11111111-1111-4111-8111-111111111111", "name": "ns-db"},
            {
                "uuid": "22222222-2222-4222-8222-222222222222",
                "name": "ns-db-preview",
            },
        ]
    }

    selected = guard.select_preview_d1_database(payload)

    assert selected.database_id == "22222222-2222-4222-8222-222222222222"
    assert selected.database_name == "ns-db-preview"


def test_select_preview_d1_missing_has_dedicated_exit_code() -> None:
    with pytest.raises(guard.PreviewDatabaseMissing) as excinfo:
        guard.select_preview_d1_database({"result": [{"uuid": "x", "name": "ns-db"}]})

    assert excinfo.value.exit_code == guard.PREVIEW_D1_MISSING_EXIT


def test_select_preview_d1_rejects_ambiguous_or_invalid_payloads() -> None:
    with pytest.raises(guard.PreviewGuardError):
        guard.select_preview_d1_database(
            [
                {"uuid": "1", "name": "ns-db-preview"},
                {"uuid": "2", "name": "ns-db-preview"},
            ]
        )

    with pytest.raises(guard.PreviewGuardError):
        guard.select_preview_d1_database({"unexpected": "shape"})


def test_render_preview_config_replaces_placeholder_exactly_once(tmp_path: Path) -> None:
    source = tmp_path / "wrangler.toml"
    output = tmp_path / "wrangler.preview.toml"
    source.write_text(
        """
[[env.preview.d1_databases]]
binding = "DB"
database_name = "ns-db-preview"
database_id = "00000000-0000-4000-8000-000000000000"
""".strip(),
        encoding="utf-8",
    )

    guard.render_preview_config(
        source,
        output,
        database_id="22222222-2222-4222-8222-222222222222",
    )

    rendered = output.read_text(encoding="utf-8")
    assert "00000000-0000-4000-8000-000000000000" not in rendered
    assert "22222222-2222-4222-8222-222222222222" in rendered

    source.write_text("database_id = \"no-placeholder\"\n", encoding="utf-8")
    with pytest.raises(guard.PreviewGuardError):
        guard.render_preview_config(source, output, database_id="x")


def test_build_preview_seed_sql_contains_fresh_event_ops_and_snapshots(
    tmp_path: Path,
) -> None:
    sql = guard.build_preview_seed_sql(
        now_iso="2026-08-02T00:00:00Z",
        deploy_commit="abc123",
        run_id="run-7",
    )

    assert not sql.lstrip().startswith("#")
    assert sql.startswith("INSERT OR REPLACE INTO targets")
    assert "preview-smoke-run-7" in sql
    assert "INSERT OR REPLACE INTO events" in sql
    assert "INSERT OR REPLACE INTO ops_state" in sql
    assert "last:collect-cycle" in sql
    assert "last:public-translation-cycle" in sql
    assert "last:refresh-public-quality" in sql
    assert "INSERT OR REPLACE INTO public_read_snapshots" in sql
    assert "news:featured:v1:page_size=20" in sql
    assert "bootstrap:featured:v1:page_size=20" in sql
    assert "facets:v1" in sql
    assert "regions:active:v1" in sql
    assert "abc123" in sql

    connection = sqlite3.connect(tmp_path / "preview.db")
    try:
        connection.executescript(
            (ROOT / "frontend/cloudflare/db/schema.sql").read_text(encoding="utf-8")
        )
        connection.executescript(sql)
        row = connection.execute(
            "SELECT target_id, config_version FROM source_runtime_state "
            "WHERE source_id = 'preview-seed'"
        ).fetchone()
        migration_receipts = {
            result[0]
            for result in connection.execute(
                "SELECT migration_id FROM runtime_migration_receipts"
            ).fetchall()
        }
        snapshot_sizes = connection.execute(
            "SELECT payload_json, payload_bytes FROM public_read_snapshots"
        ).fetchall()
    finally:
        connection.close()

    assert row == ("preview", "abc123")
    assert migration_receipts == set(EXPECTED_MIGRATION_RECEIPTS)
    assert all(
        len(payload_json.encode("utf-8")) == payload_bytes
        for payload_json, payload_bytes in snapshot_sizes
    )


def test_parse_preview_deploy_receipt_validates_worker_env_and_https_target(tmp_path: Path) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        "\n".join(
            [
                json.dumps({"type": "log", "message": "deploying"}),
                json.dumps(
                    {
                        "worker_name": "news-sentry-api-preview",
                        "wrangler_environment": "preview",
                        "targets": [
                            {
                                "url": "https://news-sentry-api-preview.example.workers.dev"
                            }
                        ],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    parsed = guard.parse_preview_deploy_receipt(receipt)

    assert parsed.api_url == "https://news-sentry-api-preview.example.workers.dev"
    assert parsed.worker_name == "news-sentry-api-preview"
    assert parsed.environment == "preview"


def test_parse_preview_deploy_receipt_rejects_wrong_worker_or_non_https(tmp_path: Path) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api",
                "wrangler_environment": "preview",
                "targets": [{"url": "http://example.workers.dev"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(guard.PreviewGuardError):
        guard.parse_preview_deploy_receipt(receipt)


def test_parse_preview_deploy_receipt_requires_real_wrangler_env_and_workers_dev(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api-preview",
                "environment": "preview",
                "targets": ["https://news-sentry-api-preview.example.workers.dev"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(guard.PreviewGuardError):
        guard.parse_preview_deploy_receipt(receipt)

    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api-preview",
                "wrangler_environment": "preview",
                "targets": ["https://attacker.example/preview"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(guard.PreviewGuardError):
        guard.parse_preview_deploy_receipt(receipt)


def test_parse_preview_deploy_receipt_prefers_workers_dev_over_zone_route(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api-preview",
                "wrangler_environment": "preview",
                "targets": [
                    "preview.news-sentry.com/api/*",
                    "https://news-sentry-api-preview.example.workers.dev",
                ],
            }
        ),
        encoding="utf-8",
    )

    parsed = guard.parse_preview_deploy_receipt(receipt)

    assert parsed.api_url == "https://news-sentry-api-preview.example.workers.dev"


def _pages_project() -> dict[str, object]:
    return {
        "result": {
            "name": "news-sentry",
            "deployment_configs": {
                "production": {
                    "compatibility_date": "2026-06-24",
                    "env_vars": {"PUBLIC_ONLY": {"value": "keep-me"}},
                    "services": {},
                },
                "preview": {
                    "compatibility_date": "2026-06-24",
                    "kv_namespaces": {"KEEP": {"namespace_id": "kv"}},
                    "services": {},
                },
            },
        }
    }


def test_preview_pages_service_patch_binds_preview_worker_and_keeps_production() -> None:
    payload = _pages_project()

    patch = guard.preview_pages_service_patch(payload)

    production = patch["deployment_configs"]["production"]
    preview = patch["deployment_configs"]["preview"]
    assert production["env_vars"] == {"PUBLIC_ONLY": {"value": "keep-me"}}
    assert preview["kv_namespaces"] == {"KEEP": {"namespace_id": "kv"}}
    assert preview["services"] == {"PREVIEW_API": {"service": "news-sentry-api-preview"}}
    stored = payload["result"]["deployment_configs"]["production"]  # type: ignore[index]
    assert stored["services"] == {}


def test_preview_pages_service_patch_refuses_redacted_production_secrets() -> None:
    payload = _pages_project()
    production = payload["result"]["deployment_configs"]["production"]  # type: ignore[index]
    production["env_vars"] = {"CF_ACCESS_CLIENT_SECRET": {"value": ""}}

    with pytest.raises(guard.PreviewGuardError, match="redacted"):
        guard.preview_pages_service_patch(payload)


def test_preview_pages_service_check_rejects_production_drift() -> None:
    before = _pages_project()
    after = _pages_project()
    after_preview = after["result"]["deployment_configs"]["preview"]  # type: ignore[index]
    after_preview["services"] = {"PREVIEW_API": {"service": "news-sentry-api-preview"}}
    guard.assert_preview_pages_service_binding(before, after)

    after_production = after["result"]["deployment_configs"]["production"]  # type: ignore[index]
    after_production["services"] = {"PREVIEW_API": {"service": "news-sentry-api-preview"}}
    with pytest.raises(guard.PreviewGuardError, match="production"):
        guard.assert_preview_pages_service_binding(before, after)


def test_plan_preview_pages_dns_retargets_only_proxied_preview_cname() -> None:
    records = {
        "result": [
            {
                "id": "dns-preview",
                "type": "CNAME",
                "name": "preview.news-sentry.com",
                "content": "news-sentry.pages.dev",
                "proxied": True,
            },
            {
                "id": "dns-apex",
                "type": "CNAME",
                "name": "news-sentry.com",
                "content": "news-sentry.pages.dev",
                "proxied": True,
            },
        ]
    }

    planned = guard.plan_preview_pages_dns(
        records,
        "https://manual-preview-42083119723.news-sentry.pages.dev",
    )

    assert planned["id"] == "dns-preview"
    assert planned["record"] == {
        "type": "CNAME",
        "name": "preview.news-sentry.com",
        "content": "manual-preview-42083119723.news-sentry.pages.dev",
        "proxied": True,
        "ttl": 1,
    }
    with pytest.raises(guard.PreviewGuardError):
        guard.plan_preview_pages_dns(records, "https://news-sentry.pages.dev")
    with pytest.raises(guard.PreviewGuardError):
        guard.plan_preview_pages_dns(records, "https://news-sentry-api.example.workers.dev")


def test_preview_pages_function_forwards_original_request_only_for_preview_hosts() -> None:
    function = (ROOT / "frontend" / "public" / "functions" / "api" / "[[path]].js").read_text(
        encoding="utf-8"
    )
    assert "return api.fetch(context.request)" in function
    assert "workers.dev" not in function
    assert "api.news-sentry.com" not in function
    assert "context.next()" in function

    script = """
import { previewApiProxyHost } from "./frontend/public/functions/preview-api-host.js";
const cases = [
  ["preview.news-sentry.com", true],
  ["835a7715.news-sentry.pages.dev", true],
  ["manual-preview-1.news-sentry.pages.dev", true],
  ["news-sentry.pages.dev", false],
  ["news-sentry.com", false],
  ["www.news-sentry.com", false],
  ["api.news-sentry.com", false],
  ["evil.com", false],
  ["news-sentry.pages.dev.evil.com", false],
];
for (const [host, expected] of cases) {
  if (previewApiProxyHost(host) !== expected) {
    console.error(host);
    process.exit(1);
  }
}
"""
    completed = subprocess.run(  # noqa: S603 - local node checks a repository module.
        ["node", "--input-type=module", "-e", script],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
