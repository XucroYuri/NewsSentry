"""Refresh Cloudflare D1 public read snapshots from the remote D1 database."""

# ruff: noqa: S608

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NEWS_FEATURED_SNAPSHOT_KEY = "news:featured:v1:page_size=20"
NEWS_ALL_SNAPSHOT_KEY = "news:all:v1:page_size=20"
BOOTSTRAP_FEATURED_SNAPSHOT_KEY = "bootstrap:featured:v1:page_size=20"
FACETS_SNAPSHOT_KEY = "facets:v1"
REGIONS_ACTIVE_SNAPSHOT_KEY = "regions:active:v1"

PUBLIC_NEWS_SELECT_COLUMNS = """
  event_id, target_id, target_label,
  source_id, source_name, source_type, credibility_label,
  published_at, title, original_title, summary,
  recommendation_reason, full_content, original_url,
  detail_url, image_urls, tags, issue_tags, related_tags,
  region_tags, entities, related_count, discussion_count,
  value_label, value_score, china_relevance_label
"""

PUBLIC_FEATURED_MIN_SCORE = 60


def _sql(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_array(raw: Any) -> list[Any]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_json(text: str) -> Any:  # noqa: ANN401
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start_candidates = [idx for idx in (stripped.find("["), stripped.find("{")) if idx >= 0]
    if not start_candidates:
        raise ValueError("Wrangler output did not contain JSON")
    start = min(start_candidates)
    return json.loads(stripped[start:])


def parse_wrangler_d1_json_output(raw: str) -> list[dict[str, Any]]:
    """Return the first SELECT result set from `wrangler d1 execute --json` output."""

    payload = _extract_json(raw)
    if isinstance(payload, list):
        first = payload[0] if payload else {}
    elif isinstance(payload, dict):
        first = payload
    else:
        raise ValueError("Unexpected Wrangler JSON output")
    results = first.get("results") if isinstance(first, dict) else None
    return list(results) if isinstance(results, list) else []


def _run_wrangler_query(
    *,
    wrangler_dir: Path,
    database: str,
    sql: str,
    remote: bool,
) -> list[dict[str, Any]]:
    command = ["npx", "wrangler", "d1", "execute", database, "--json", "--command", sql]
    command.append("--remote" if remote else "--local")
    result = subprocess.run(
        command,
        cwd=wrangler_dir,
        check=True,
        text=True,
        capture_output=True,
    )
    return parse_wrangler_d1_json_output(result.stdout)


def _public_news_where(featured: bool) -> str:
    where = "WHERE pipeline_stage = 'drafts'"
    if not featured:
        return where
    return (
        where
        + f"""
      AND value_score >= {PUBLIC_FEATURED_MIN_SCORE}
      AND summary IS NOT NULL
      AND TRIM(summary) != ''
      AND recommendation_reason IS NOT NULL
      AND TRIM(recommendation_reason) != ''
      AND json_valid(classification) = 1
      AND COALESCE(NULLIF(LOWER(TRIM(json_extract(classification, '$.l0'))), ''), 'uncategorized')
          NOT IN ('uncategorized', 'other', 'breaking_news')
      AND COALESCE(original_url, '') NOT LIKE '%/opinion/todayinhistory/%'
      AND NOT (
        UPPER(TRIM(title)) LIKE 'MONDAY, %'
        OR UPPER(TRIM(title)) LIKE 'TUESDAY, %'
        OR UPPER(TRIM(title)) LIKE 'WEDNESDAY, %'
        OR UPPER(TRIM(title)) LIKE 'THURSDAY, %'
        OR UPPER(TRIM(title)) LIKE 'FRIDAY, %'
        OR UPPER(TRIM(title)) LIKE 'SATURDAY, %'
        OR UPPER(TRIM(title)) LIKE 'SUNDAY, %'
      )
    """
    )


def _public_news_order_by(featured: bool) -> str:
    return (
        "ORDER BY value_score DESC, published_at DESC, event_id DESC"
        if featured
        else "ORDER BY published_at DESC, event_id DESC"
    )


def _news_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("event_id"),
        "targetId": row.get("target_id"),
        "targetLabel": row.get("target_label") or "",
        "source": {
            "id": row.get("source_id"),
            "name": row.get("source_name") or row.get("source_id") or "",
            "type": row.get("source_type") or "unknown",
            "credibilityLabel": row.get("credibility_label"),
        },
        "publishedAt": row.get("published_at"),
        "title": row.get("title") or "",
        "originalTitle": row.get("original_title"),
        "summary": row.get("summary"),
        "recommendationReason": row.get("recommendation_reason"),
        "fullContent": row.get("full_content"),
        "imageUrls": _json_array(row.get("image_urls")),
        "originalUrl": row.get("original_url"),
        "detailUrl": row.get("detail_url") or f"/public-app/news/{row.get('event_id')}",
        "tags": _json_array(row.get("tags")),
        "issueTags": _json_array(row.get("issue_tags")),
        "relatedTags": _json_array(row.get("related_tags")),
        "regionTags": _json_array(row.get("region_tags")),
        "entities": _json_array(row.get("entities")),
        "relatedCount": row.get("related_count") or 0,
        "discussionCount": row.get("discussion_count"),
        "valueLabel": row.get("value_label") or "普通",
        "valueScore": row.get("value_score"),
        "chinaRelevanceLabel": row.get("china_relevance_label") or "未知",
    }


def _feed_payload(rows: list[dict[str, Any]], total: int) -> dict[str, Any]:
    page_rows = rows[:20]
    return {
        "items": [_news_item(row) for row in page_rows],
        "latestCursor": page_rows[0].get("event_id") if page_rows else None,
        "nextCursor": page_rows[-1].get("event_id") if len(rows) > 20 and page_rows else None,
        "pollAfterMs": 60000,
        "hasNewer": False,
        "total": total,
    }


def _query_news_feed(
    *,
    wrangler_dir: Path,
    database: str,
    featured: bool,
    remote: bool,
) -> dict[str, Any]:
    where = _public_news_where(featured)
    rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=(
            f"SELECT {PUBLIC_NEWS_SELECT_COLUMNS} FROM events "
            f"{where} {_public_news_order_by(featured)} LIMIT 21"
        ),  # noqa: S608
    )
    count_rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=f"SELECT COUNT(*) AS total FROM events {where}",  # noqa: S608
    )
    total = int((count_rows[0] if count_rows else {}).get("total") or len(rows))
    return _feed_payload(rows, total)


def _query_facets(*, wrangler_dir: Path, database: str, remote: bool) -> dict[str, Any]:
    region_rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=(
            "SELECT region_id AS id, region_id AS label, COUNT(*) AS count "
            "FROM events WHERE pipeline_stage = 'drafts' "
            "GROUP BY region_id ORDER BY count DESC"
        ),
    )
    issue_rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=(
            "SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count "
            "FROM events, json_each(events.issue_tags) "
            "WHERE events.pipeline_stage = 'drafts' "
            "GROUP BY json_each.value ORDER BY count DESC"
        ),
    )
    related_rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=(
            "SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count "
            "FROM events, json_each(events.related_tags) "
            "WHERE events.pipeline_stage = 'drafts' "
            "GROUP BY json_each.value ORDER BY count DESC"
        ),
    )
    return {
        "regions": region_rows,
        "issues": issue_rows,
        "related": related_rows,
    }


def _query_regions(*, wrangler_dir: Path, database: str, remote: bool) -> dict[str, Any]:
    rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=(
            "SELECT target_id, display_name, region_id, primary_language, region_type, "
            "source_count, event_count, lifecycle, archived "
            "FROM targets WHERE archived = 0 "
            "ORDER BY event_count DESC, display_name ASC LIMIT 200"
        ),
    )
    regions = []
    for row in rows:
        if int(row.get("event_count") or 0) <= 0 and int(row.get("source_count") or 0) <= 0:
            continue
        regions.append(
            {
                "region_id": row.get("region_id") or row.get("target_id"),
                "display_name": row.get("display_name"),
                "primary_language": row.get("primary_language") or "en",
                "region_type": row.get("region_type") or "country",
                "source_count": row.get("source_count") or 0,
                "event_count": row.get("event_count") or 0,
                "lifecycle": _json_object(row.get("lifecycle")),
                "archived": bool(row.get("archived")),
            }
        )
    return {"regions": regions}


def _latest_public_at(*, wrangler_dir: Path, database: str, remote: bool) -> str | None:
    rows = _run_wrangler_query(
        wrangler_dir=wrangler_dir,
        database=database,
        remote=remote,
        sql=(
            "SELECT MAX(published_at) AS latest_public_at "
            "FROM events WHERE pipeline_stage = 'drafts'"
        ),
    )
    if rows and rows[0].get("latest_public_at"):
        return str(rows[0].get("latest_public_at"))
    return None


def collect_snapshot_payloads(
    *,
    wrangler_dir: Path,
    database: str,
    remote: bool,
) -> tuple[dict[str, Any], str | None]:
    featured_news = _query_news_feed(
        wrangler_dir=wrangler_dir,
        database=database,
        featured=True,
        remote=remote,
    )
    all_news = _query_news_feed(
        wrangler_dir=wrangler_dir,
        database=database,
        featured=False,
        remote=remote,
    )
    facets = _query_facets(wrangler_dir=wrangler_dir, database=database, remote=remote)
    regions = _query_regions(wrangler_dir=wrangler_dir, database=database, remote=remote)
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    bootstrap = {
        "news": featured_news,
        "regions": regions,
        "facets": facets,
        "generatedAt": generated_at,
    }
    return (
        {
            NEWS_FEATURED_SNAPSHOT_KEY: featured_news,
            NEWS_ALL_SNAPSHOT_KEY: all_news,
            BOOTSTRAP_FEATURED_SNAPSHOT_KEY: bootstrap,
            FACETS_SNAPSHOT_KEY: facets,
            REGIONS_ACTIVE_SNAPSHOT_KEY: regions,
        },
        _latest_public_at(wrangler_dir=wrangler_dir, database=database, remote=remote),
    )


def _item_count(key: str, payload: Any) -> int:  # noqa: ANN401
    if not isinstance(payload, dict):
        return 0
    if key == FACETS_SNAPSHOT_KEY:
        return sum(len(payload.get(name) or []) for name in ("regions", "issues", "related"))
    if key == REGIONS_ACTIVE_SNAPSHOT_KEY:
        return len(payload.get("regions") or [])
    if key == BOOTSTRAP_FEATURED_SNAPSHOT_KEY:
        news = payload.get("news") if isinstance(payload.get("news"), dict) else {}
        return len(news.get("items") or [])
    return len(payload.get("items") or [])


def build_snapshot_upsert_sql(
    payloads: Mapping[str, Any],
    *,
    generated_at: str,
    source_latest_public_at: str | None,
) -> str:
    statements = ["BEGIN TRANSACTION;"]
    for key in (
        NEWS_FEATURED_SNAPSHOT_KEY,
        NEWS_ALL_SNAPSHOT_KEY,
        BOOTSTRAP_FEATURED_SNAPSHOT_KEY,
        FACETS_SNAPSHOT_KEY,
        REGIONS_ACTIVE_SNAPSHOT_KEY,
    ):
        payload = payloads[key]
        payload_json = _json(payload)
        statements.append(
            "INSERT INTO public_read_snapshots "
            "(key, payload_json, generated_at, source_latest_public_at, item_count, "
            "payload_bytes, updated_at) VALUES "
            f"({_sql(key)}, {_sql(payload_json)}, {_sql(generated_at)}, "
            f"{_sql(source_latest_public_at)}, {_item_count(key, payload)}, "
            f"{len(payload_json.encode('utf-8'))}, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET "
            "payload_json=excluded.payload_json, "
            "generated_at=excluded.generated_at, "
            "source_latest_public_at=excluded.source_latest_public_at, "
            "item_count=excluded.item_count, "
            "payload_bytes=excluded.payload_bytes, "
            "updated_at=excluded.updated_at;"
        )  # noqa: S608
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrangler-dir", type=Path, default=Path("frontend/cloudflare"))
    parser.add_argument("--database", default="ns-db")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--output-sql", type=Path, required=True)
    args = parser.parse_args()

    payloads, source_latest_public_at = collect_snapshot_payloads(
        wrangler_dir=args.wrangler_dir,
        database=args.database,
        remote=not args.local,
    )
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sql = build_snapshot_upsert_sql(
        payloads,
        generated_at=generated_at,
        source_latest_public_at=source_latest_public_at,
    )
    args.output_sql.write_text(sql, encoding="utf-8")
    print(
        "wrote "
        f"{args.output_sql} "
        f"featured={_item_count(NEWS_FEATURED_SNAPSHOT_KEY, payloads[NEWS_FEATURED_SNAPSHOT_KEY])} "
        f"regions={_item_count(REGIONS_ACTIVE_SNAPSHOT_KEY, payloads[REGIONS_ACTIVE_SNAPSHOT_KEY])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
