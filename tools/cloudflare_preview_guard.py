# ruff: noqa: S608
"""Fail-closed helpers for isolated Cloudflare preview Worker deployment."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS  # noqa: E402

PREVIEW_DATABASE_NAME = "ns-db-preview"
PREVIEW_WORKER_NAME = "news-sentry-api-preview"
PRODUCTION_WORKER_NAME = "news-sentry-api"
PREVIEW_ENVIRONMENT = "preview"
PREVIEW_PAGES_PROJECT = "news-sentry"
PREVIEW_PAGES_BINDING = "PREVIEW_API"
PREVIEW_CUSTOM_HOST = "preview.news-sentry.com"
PAGES_APEX_HOST = "news-sentry.pages.dev"
_PRODUCTION_CONFIG_KEYS = (
    "env_vars",
    "kv_namespaces",
    "d1_databases",
    "r2_buckets",
    "durable_object_namespaces",
    "services",
    "compatibility_date",
    "compatibility_flags",
)
_REDACTED_ENV_VALUES = {"", "***", "[REDACTED]", "REDACTED"}
PREVIEW_D1_PLACEHOLDER = "00000000-0000-4000-8000-000000000000"
PREVIEW_D1_MISSING_EXIT = 42
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class PreviewGuardError(RuntimeError):
    """Preview guard failed closed."""

    exit_code = 2


class PreviewDatabaseMissing(PreviewGuardError):  # noqa: N818
    """The isolated preview D1 database does not exist yet."""

    exit_code = PREVIEW_D1_MISSING_EXIT


@dataclass(frozen=True)
class PreviewDatabase:
    database_name: str
    database_id: str


@dataclass(frozen=True)
class PreviewDeployReceipt:
    worker_name: str
    environment: str
    api_url: str


def _rows(payload: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    if isinstance(payload, list):
        if all(isinstance(item, dict) for item in payload):
            return payload
        raise PreviewGuardError("Invalid Wrangler D1 list payload: list contains non-objects")
    if isinstance(payload, dict):
        for key in ("result", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value
    raise PreviewGuardError("Invalid Wrangler D1 list payload: expected result/results/items list")


def select_preview_d1_database(payload: Any) -> PreviewDatabase:  # noqa: ANN401
    matches = [row for row in _rows(payload) if row.get("name") == PREVIEW_DATABASE_NAME]
    if not matches:
        raise PreviewDatabaseMissing(f"{PREVIEW_DATABASE_NAME} is missing")
    if len(matches) != 1:
        raise PreviewGuardError(f"{PREVIEW_DATABASE_NAME} is ambiguous: {len(matches)} matches")

    database_id = str(matches[0].get("uuid") or matches[0].get("id") or "").strip()
    if not _UUID_RE.match(database_id):
        raise PreviewGuardError(f"{PREVIEW_DATABASE_NAME} id is not UUID-shaped")
    return PreviewDatabase(database_name=PREVIEW_DATABASE_NAME, database_id=database_id)


def render_preview_config(source: Path, output: Path, *, database_id: str) -> None:
    if not _UUID_RE.match(database_id):
        raise PreviewGuardError("Preview D1 database id is not UUID-shaped")
    text = source.read_text(encoding="utf-8")
    count = text.count(PREVIEW_D1_PLACEHOLDER)
    if count != 1:
        raise PreviewGuardError(
            f"Preview D1 placeholder must appear exactly once; found {count}"
        )
    output.write_text(text.replace(PREVIEW_D1_PLACEHOLDER, database_id), encoding="utf-8")


def _sql_text(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _json_text(value: Any) -> str:  # noqa: ANN401
    return _sql_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _json_bytes(value: Any) -> int:  # noqa: ANN401
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return len(payload.encode("utf-8"))


def _preview_item(event_id: str, now_iso: str, deploy_commit: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "targetId": "preview",
        "targetLabel": "Preview",
        "source": {
            "id": "preview-seed",
            "name": "News Sentry Preview Seed",
            "type": "synthetic",
            "credibilityLabel": "official",
        },
        "publishedAt": now_iso,
        "title": "News Sentry preview runtime seed",
        "originalTitle": "News Sentry preview runtime seed",
        "summary": f"Fresh synthetic preview event for {deploy_commit}.",
        "recommendationReason": "Validates the isolated Cloudflare preview runtime.",
        "fullContent": "Preview-only seed data; not production content.",
        "originalUrl": "https://preview.news-sentry.com/",
        "detailUrl": f"/public-app/news/{event_id}",
        "imageUrls": [],
        "tags": ["preview"],
        "issueTags": ["operations"],
        "relatedTags": ["runtime"],
        "regionTags": ["preview"],
        "entities": [],
        "relatedCount": 0,
        "discussionCount": 0,
        "valueLabel": "高价值",
        "valueScore": 90,
        "breakingScore": 90,
        "breakingLabel": "preview",
        "breakingReason": "Synthetic preview runtime proof",
        "breakingConfidence": 100,
        "breakingDimensions": {},
        "targetTimezone": "UTC",
        "publishedAtLocal": now_iso,
        "availableLocales": [],
        "chinaRelevanceLabel": "中",
    }


def build_preview_seed_sql(*, now_iso: str, deploy_commit: str, run_id: str) -> str:
    event_id = f"preview-smoke-{re.sub(r'[^A-Za-z0-9_.-]+', '-', run_id).strip('-') or 'run'}"
    item = _preview_item(event_id, now_iso, deploy_commit)
    feed = {
        "items": [item],
        "latestCursor": event_id,
        "nextCursor": None,
        "pollAfterMs": 30000,
        "hasNewer": False,
        "total": 1,
    }
    facets = {
        "regions": [{"id": "preview", "label": "Preview", "count": 1}],
        "issues": [{"id": "operations", "label": "operations", "count": 1}],
        "related": [{"id": "runtime", "label": "runtime", "count": 1}],
    }
    bootstrap = {"news": feed, "facets": facets}
    regions = {
        "regions": [
            {
                "id": "preview",
                "label": "Preview",
                "primaryLanguage": "en",
                "regionType": "preview",
                "targetCount": 1,
                "eventCount": 1,
            }
        ]
    }
    ops_value = {"status": "ok", "deploy_commit": deploy_commit, "run_id": run_id}
    snapshots = {
        "news:featured:v1:page_size=20": feed,
        "news:all:v1:page_size=20": feed,
        "bootstrap:featured:v1:page_size=20": bootstrap,
        "facets:v1": facets,
        "regions:active:v1": regions,
    }
    snapshot_rows = "\n".join(  # noqa: S608 - generated seed SQL uses escaped literals.
        "INSERT OR REPLACE INTO public_read_snapshots "
        "(key, payload_json, generated_at, source_latest_public_at, "
        "item_count, payload_bytes, updated_at) "
        f"VALUES ({_sql_text(key)}, {_json_text(payload)}, {_sql_text(now_iso)}, "
        f"{_sql_text(now_iso)}, 1, {_json_bytes(payload)}, {_sql_text(now_iso)});"
        for key, payload in snapshots.items()
    )
    migration_receipt_rows = "\n".join(
        "INSERT OR IGNORE INTO runtime_migration_receipts "
        "(migration_id, deploy_commit, details_json) "
        f"VALUES ({_sql_text(migration_id)}, {_sql_text(deploy_commit)}, "
        f"{_json_text({'recorded_by': 'preview_fresh_schema'})});"
        for migration_id in EXPECTED_MIGRATION_RECEIPTS
    )
    return f"""INSERT OR REPLACE INTO targets
  (target_id, display_name, region_id, primary_language, region_type, source_count,
   event_count, cloudflare_collect_enabled, timezone)
VALUES ('preview', 'Preview', 'preview', 'en', 'preview', 1, 1, 0, 'UTC');

INSERT OR REPLACE INTO events
  (event_id, target_id, target_label, region_id, source_id, source_name, source_type,
   credibility_label, published_at, collected_at, title, original_title, summary,
   recommendation_reason, full_content, original_url, detail_url, image_urls, tags,
   issue_tags, related_tags, region_tags, entities, language, pipeline_stage,
   processing_history, value_label, value_score, china_relevance_label, related_count,
   discussion_count, classification, extra, breaking_score, breaking_label,
   breaking_reason, breaking_confidence, breaking_dimensions, breaking_score_version,
   target_timezone, published_at_local, updated_at)
VALUES
  ({_sql_text(event_id)}, 'preview', 'Preview', 'preview', 'preview-seed',
   'News Sentry Preview Seed', 'synthetic', 'official', {_sql_text(now_iso)},
   {_sql_text(now_iso)}, 'News Sentry preview runtime seed',
   'News Sentry preview runtime seed',
   {_sql_text(item["summary"])}, {_sql_text(item["recommendationReason"])},
   'Preview-only seed data; not production content.',
   'https://preview.news-sentry.com/', '/public-app/news/{event_id}', '[]',
   '["preview"]', '["operations"]', '["runtime"]', '["preview"]', '[]', 'en',
   'drafts', '[]', '高价值', 90, '中', 0, 0,
   '{{"l0":"operations","l1":"runtime"}}',
   {_json_text({"preview": True, "deploy_commit": deploy_commit, "run_id": run_id})},
   90, 'preview', 'Synthetic preview runtime proof', 100, '{{}}',
   'breaking-v1.0', 'UTC', {_sql_text(now_iso)}, {_sql_text(now_iso)});

INSERT OR REPLACE INTO source_runtime_state
  (target_id, source_id, tier, capability, state, next_due_at, last_attempt_at,
   last_success_at, consecutive_failures, config_version, updated_at)
VALUES
  ('preview', 'preview-seed', 'P2', 'preview-seed', 'active', {_sql_text(now_iso)},
   {_sql_text(now_iso)}, {_sql_text(now_iso)}, 0, {_sql_text(deploy_commit)},
   {_sql_text(now_iso)});

INSERT OR REPLACE INTO ops_state (key, value, updated_at)
VALUES
  ('last:collect-cycle', {_json_text(ops_value)}, {_sql_text(now_iso)}),
  ('last:public-translation-cycle', {_json_text(ops_value)}, {_sql_text(now_iso)}),
  ('last:refresh-public-quality', {_json_text(ops_value)}, {_sql_text(now_iso)});

{migration_receipt_rows}

{snapshot_rows}
""".strip() + "\n"


def write_preview_seed_sql(output: Path, *, deploy_commit: str, run_id: str) -> None:
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    output.write_text(
        build_preview_seed_sql(now_iso=now_iso, deploy_commit=deploy_commit, run_id=run_id),
        encoding="utf-8",
    )


def _iter_ndjson(path: Path) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PreviewGuardError(f"Invalid Wrangler deploy NDJSON: {exc}") from exc
        if isinstance(parsed, dict):
            objects.append(parsed)
    if not objects:
        raise PreviewGuardError("Wrangler deploy receipt is empty")
    return objects


def _iter_target_strings(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("target", "url"):
        value = candidate.get(key)
        if isinstance(value, str):
            values.append(value)
    targets = candidate.get("targets")
    if isinstance(targets, list):
        for item in targets:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                for key in ("url", "target"):
                    item_url = item.get(key)
                    if isinstance(item_url, str):
                        values.append(item_url)
                        break
    return values


def _canonical_workers_dev_origin(api_url: str) -> str | None:
    parsed_url = urlparse(api_url)
    hostname = parsed_url.hostname or ""
    if (
        parsed_url.scheme != "https"
        or not hostname.startswith(f"{PREVIEW_WORKER_NAME}.")
        or not hostname.endswith(".workers.dev")
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.port not in (None, 443)
        or parsed_url.path not in ("", "/")
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
    ):
        return None
    return api_url.rstrip("/")


def parse_preview_deploy_receipt(path: Path) -> PreviewDeployReceipt:
    for candidate in reversed(_iter_ndjson(path)):
        worker_name = str(candidate.get("worker_name") or candidate.get("workerName") or "").strip()
        environment = str(candidate.get("wrangler_environment") or "").strip()
        urls = _iter_target_strings(candidate)
        if not (worker_name or environment or urls):
            continue
        if worker_name != PREVIEW_WORKER_NAME:
            raise PreviewGuardError(f"Unexpected preview Worker name: {worker_name or '<missing>'}")
        if environment != PREVIEW_ENVIRONMENT:
            raise PreviewGuardError(f"Unexpected preview environment: {environment or '<missing>'}")
        matches = [
            origin
            for url in urls
            if (origin := _canonical_workers_dev_origin(url)) is not None
        ]
        if len(matches) != 1:
            raise PreviewGuardError(
                "Preview Worker target URL must be exactly one canonical HTTPS workers.dev origin"
            )
        return PreviewDeployReceipt(
            worker_name=worker_name,
            environment=environment,
            api_url=matches[0],
        )
    raise PreviewGuardError("No preview deploy receipt found in Wrangler output")


def _project_result(payload: Any) -> dict[str, Any]:  # noqa: ANN401
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        return payload["result"]
    if isinstance(payload, dict):
        return payload
    raise PreviewGuardError("Pages project payload is not an object")


def _deployment_configs(project: dict[str, Any]) -> dict[str, Any]:
    configs = project.get("deployment_configs")
    if not isinstance(configs, dict):
        raise PreviewGuardError("Pages project is missing deployment_configs")
    return configs


def _env_var_value(spec: Any) -> Any:  # noqa: ANN401
    if isinstance(spec, dict) and "value" in spec:
        return spec.get("value")
    return spec


def _assert_round_trippable(config: dict[str, Any], label: str) -> None:
    env_vars = config.get("env_vars") or {}
    if not isinstance(env_vars, dict):
        raise PreviewGuardError(f"{label} env_vars is invalid")
    for key, spec in env_vars.items():
        value = _env_var_value(spec)
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if normalized in _REDACTED_ENV_VALUES:
            raise PreviewGuardError(
                f"{label} env var {key} is redacted; refusing to rewrite Pages config"
            )


def _service_name(spec: Any) -> str | None:  # noqa: ANN401
    if isinstance(spec, dict):
        service = spec.get("service")
        if isinstance(service, str):
            return service
    return None


def preview_pages_service_patch(payload: Any) -> dict[str, Any]:  # noqa: ANN401
    """Add the preview Worker binding without retargeting production Pages."""
    configs = _deployment_configs(_project_result(payload))
    production = configs.get("production")
    preview = configs.get("preview")
    if not isinstance(production, dict) or not isinstance(preview, dict):
        raise PreviewGuardError("Pages production and preview configs are required")
    _assert_round_trippable(production, "production")
    _assert_round_trippable(preview, "preview")

    merged_preview = copy.deepcopy(preview)
    services = merged_preview.get("services") or {}
    if not isinstance(services, dict):
        raise PreviewGuardError("Pages preview services config is invalid")
    services = dict(services)
    for spec in services.values():
        if _service_name(spec) == PRODUCTION_WORKER_NAME:
            raise PreviewGuardError("Preview Pages must not bind the production Worker")
    services[PREVIEW_PAGES_BINDING] = {"service": PREVIEW_WORKER_NAME}
    merged_preview["services"] = services
    if _service_name(services[PREVIEW_PAGES_BINDING]) != PREVIEW_WORKER_NAME:
        raise PreviewGuardError("Preview Pages service binding is invalid")
    return {
        "deployment_configs": {
            "production": copy.deepcopy(production),
            "preview": merged_preview,
        }
    }


def _fingerprint(config: Any) -> dict[str, Any]:  # noqa: ANN401
    if not isinstance(config, dict):
        return {}
    fingerprinted: dict[str, Any] = {}
    for key in _PRODUCTION_CONFIG_KEYS:
        value = config.get(key)
        if value in (None, {}, []):
            continue
        fingerprinted[key] = value
    return fingerprinted


def assert_preview_pages_service_binding(before: Any, after: Any) -> None:  # noqa: ANN401
    before_configs = _deployment_configs(_project_result(before))
    after_configs = _deployment_configs(_project_result(after))
    if _fingerprint(before_configs.get("production")) != _fingerprint(
        after_configs.get("production")
    ):
        raise PreviewGuardError("Pages production deployment config changed")
    preview = after_configs.get("preview")
    if not isinstance(preview, dict):
        raise PreviewGuardError("Pages preview deployment config is missing after patch")
    services = preview.get("services") if isinstance(preview.get("services"), dict) else {}
    bound = _service_name(services.get(PREVIEW_PAGES_BINDING))
    if bound != PREVIEW_WORKER_NAME:
        raise PreviewGuardError("Preview Pages service binding PREVIEW_API is missing")
    production_services = (after_configs.get("production") or {}).get("services") or {}
    if isinstance(production_services, dict) and any(
        _service_name(spec) == PREVIEW_WORKER_NAME for spec in production_services.values()
    ):
        raise PreviewGuardError("Production Pages must not bind the preview Worker")


def select_news_sentry_zone_id(payload: Any) -> str:  # noqa: ANN401
    zones = _rows(payload)
    matches = [zone for zone in zones if zone.get("name") == "news-sentry.com"]
    if len(matches) != 1:
        raise PreviewGuardError(f"news-sentry.com zone is not unique: {len(matches)} matches")
    zone_id = str(matches[0].get("id") or "").strip()
    if not zone_id:
        raise PreviewGuardError("news-sentry.com zone id is missing")
    return zone_id


def _hostname(value: str) -> str:
    return value.strip().rstrip(".").lower()


def plan_preview_pages_dns(records_payload: Any, alias_url: str) -> dict[str, Any]:  # noqa: ANN401
    """Point the proxied preview CNAME at this deploy's Pages branch alias."""
    parsed = urlparse(alias_url.strip())
    alias_host = _hostname(parsed.hostname or "")
    if (
        parsed.scheme != "https"
        or not alias_host.endswith(f".{PAGES_APEX_HOST}")
        or alias_host == PAGES_APEX_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise PreviewGuardError(
            "Preview Pages alias must be a non-production https://*.news-sentry.pages.dev URL"
        )
    matches = [
        record
        for record in _rows(records_payload)
        if _hostname(str(record.get("name") or "")) == PREVIEW_CUSTOM_HOST
    ]
    if len(matches) != 1:
        raise PreviewGuardError(
            f"{PREVIEW_CUSTOM_HOST} DNS record is not unique: {len(matches)} matches"
        )
    record = matches[0]
    if str(record.get("type") or "").upper() != "CNAME":
        raise PreviewGuardError(f"{PREVIEW_CUSTOM_HOST} DNS record must be a CNAME")
    if record.get("proxied") is not True:
        raise PreviewGuardError(f"{PREVIEW_CUSTOM_HOST} DNS record must stay proxied")
    current = _hostname(str(record.get("content") or ""))
    if current != PAGES_APEX_HOST and not current.endswith(f".{PAGES_APEX_HOST}"):
        raise PreviewGuardError(
            f"{PREVIEW_CUSTOM_HOST} CNAME is not a news-sentry.pages.dev alias"
        )
    record_id = str(record.get("id") or "").strip()
    if not record_id:
        raise PreviewGuardError(f"{PREVIEW_CUSTOM_HOST} DNS record id is missing")
    return {
        "id": record_id,
        "record": {
            "type": "CNAME",
            "name": PREVIEW_CUSTOM_HOST,
            "content": alias_host,
            "proxied": True,
            "ttl": 1,
        },
    }


def _load_json(path: Path) -> Any:  # noqa: ANN401
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select-d1")
    select.add_argument("--input", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)

    render = subparsers.add_parser("render-config")
    render.add_argument("--source", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--database-id", required=True)

    seed = subparsers.add_parser("seed-sql")
    seed.add_argument("--output", type=Path, required=True)
    seed.add_argument("--deploy-commit", required=True)
    seed.add_argument("--run-id", required=True)

    receipt = subparsers.add_parser("deploy-receipt")
    receipt.add_argument("--input", type=Path, required=True)
    receipt.add_argument("--output", type=Path, required=True)
    receipt.add_argument("--github-output", type=Path)

    service_patch = subparsers.add_parser("pages-service-patch")
    service_patch.add_argument("--input", type=Path, required=True)
    service_patch.add_argument("--output", type=Path, required=True)

    service_check = subparsers.add_parser("pages-service-check")
    service_check.add_argument("--before", type=Path, required=True)
    service_check.add_argument("--after", type=Path, required=True)

    zone = subparsers.add_parser("select-zone")
    zone.add_argument("--input", type=Path, required=True)

    dns = subparsers.add_parser("preview-dns")
    dns.add_argument("--input", type=Path, required=True)
    dns.add_argument("--alias", required=True)
    dns.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "select-d1":
            selected = select_preview_d1_database(_load_json(args.input))
            args.output.write_text(json.dumps(selected.__dict__, indent=2), encoding="utf-8")
            return 0
        if args.command == "render-config":
            render_preview_config(args.source, args.output, database_id=args.database_id)
            return 0
        if args.command == "seed-sql":
            write_preview_seed_sql(
                args.output,
                deploy_commit=args.deploy_commit,
                run_id=args.run_id,
            )
            return 0
        if args.command == "deploy-receipt":
            parsed = parse_preview_deploy_receipt(args.input)
            args.output.write_text(json.dumps(parsed.__dict__, indent=2), encoding="utf-8")
            if args.github_output is not None:
                with args.github_output.open("a", encoding="utf-8") as fh:
                    fh.write(f"api_url={parsed.api_url}\n")
            return 0
        if args.command == "pages-service-patch":
            patch = preview_pages_service_patch(_load_json(args.input))
            args.output.write_text(json.dumps(patch), encoding="utf-8")
            return 0
        if args.command == "pages-service-check":
            assert_preview_pages_service_binding(_load_json(args.before), _load_json(args.after))
            return 0
        if args.command == "select-zone":
            print(select_news_sentry_zone_id(_load_json(args.input)))
            return 0
        if args.command == "preview-dns":
            planned = plan_preview_pages_dns(_load_json(args.input), args.alias)
            args.output.write_text(json.dumps(planned["record"]), encoding="utf-8")
            print(planned["id"])
            return 0
    except PreviewGuardError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    raise AssertionError(f"Unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
