# ruff: noqa: S608
"""Fail-closed helpers for isolated Cloudflare preview Worker deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PREVIEW_DATABASE_NAME = "ns-db-preview"
PREVIEW_WORKER_NAME = "news-sentry-api-preview"
PREVIEW_ENVIRONMENT = "preview"
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
        f"{_sql_text(now_iso)}, 1, LENGTH({_json_text(payload)}), {_sql_text(now_iso)});"
        for key, payload in snapshots.items()
    )
    return f"""  # noqa: S608 - generated seed SQL uses escaped literals.
INSERT OR REPLACE INTO targets
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
   last_success_at, consecutive_failures, payload_bytes, committed_at)
VALUES
  ('preview', 'preview-seed', 'P2', 'preview-seed', 'active', {_sql_text(now_iso)},
   {_sql_text(now_iso)}, {_sql_text(now_iso)}, 0, 0, {_sql_text(now_iso)});

INSERT OR REPLACE INTO ops_state (key, value, updated_at)
VALUES
  ('last:collect-cycle', {_json_text(ops_value)}, {_sql_text(now_iso)}),
  ('last:public-translation-cycle', {_json_text(ops_value)}, {_sql_text(now_iso)}),
  ('last:refresh-public-quality', {_json_text(ops_value)}, {_sql_text(now_iso)});

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


def _target_url(candidate: dict[str, Any]) -> str | None:
    target = candidate.get("target")
    if isinstance(target, str):
        return target
    url = candidate.get("url")
    if isinstance(url, str):
        return url
    targets = candidate.get("targets")
    if isinstance(targets, list):
        for item in targets:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                item_url = item.get("url")
                if isinstance(item_url, str):
                    return item_url
    return None


def parse_preview_deploy_receipt(path: Path) -> PreviewDeployReceipt:
    for candidate in reversed(_iter_ndjson(path)):
        worker_name = str(candidate.get("worker_name") or candidate.get("workerName") or "").strip()
        environment = str(candidate.get("wrangler_environment") or "").strip()
        api_url = _target_url(candidate)
        if not (worker_name or environment or api_url):
            continue
        if worker_name != PREVIEW_WORKER_NAME:
            raise PreviewGuardError(f"Unexpected preview Worker name: {worker_name or '<missing>'}")
        if environment != PREVIEW_ENVIRONMENT:
            raise PreviewGuardError(f"Unexpected preview environment: {environment or '<missing>'}")
        if api_url is None:
            raise PreviewGuardError("Preview Worker target URL is missing")
        parsed_url = urlparse(api_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or not parsed_url.hostname.endswith(".workers.dev")
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.port not in (None, 443)
            or parsed_url.path not in ("", "/")
            or parsed_url.params
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise PreviewGuardError(
                "Preview Worker target URL must be a canonical HTTPS workers.dev origin"
            )
        return PreviewDeployReceipt(
            worker_name=worker_name,
            environment=environment,
            api_url=api_url.rstrip("/"),
        )
    raise PreviewGuardError("No preview deploy receipt found in Wrangler output")


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
    except PreviewGuardError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    raise AssertionError(f"Unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
