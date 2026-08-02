#!/usr/bin/env python3
"""Deterministic, secret-free Cloudflare preview import canary helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

PREVIEW_API_ORIGIN = "https://news-sentry-api-preview.xuyu.workers.dev"
PREVIEW_IMPORT_URL = f"{PREVIEW_API_ORIGIN}/api/v1/events/import"
SCHEMA_VERSION = "2026-08-02.cloudflare-preview-canary.v1"
EVIDENCE_SQL_TEMPLATE = """
WITH expected(batch_id, job_id, artifact_id) AS (
  SELECT '__BATCH_ID__', '__JOB_ID__', '__ARTIFACT_ID__'
)
SELECT
  expected.batch_id,
  batch.status AS batch_status,
  batch.checksum AS batch_checksum,
  (SELECT COUNT(*) AS batch_count FROM import_batches WHERE batch_id = expected.batch_id)
    AS batch_count,
  expected.job_id,
  job.status AS job_status,
  (SELECT COUNT(*) AS job_count FROM jobs WHERE job_id = expected.job_id) AS job_count,
  expected.artifact_id,
  artifact.batch_id AS artifact_batch_id,
  artifact.job_id AS artifact_job_id,
  artifact.object_key AS artifact_key,
  artifact.sha256 AS artifact_sha256,
  artifact.payload_bytes AS artifact_bytes,
  artifact.status AS artifact_status,
  (SELECT COUNT(*) AS artifact_count FROM artifact_manifests
    WHERE artifact_id = expected.artifact_id
      AND batch_id = expected.batch_id
      AND job_id = expected.job_id) AS artifact_count,
  (SELECT COUNT(*) AS projection_receipt_count FROM import_projection_finalize_receipts
    WHERE batch_id = expected.batch_id AND job_id = expected.job_id
      AND artifact_id = expected.artifact_id) AS projection_receipt_count,
  receipt.batch_guard AS projection_batch_guard,
  receipt.job_guard AS projection_job_guard,
  receipt.artifact_guard AS projection_artifact_guard,
  receipt.batch_checksum AS projection_batch_checksum,
  (SELECT COUNT(*) AS event_count FROM import_staged_events
    WHERE batch_id = expected.batch_id)
    AS event_count
FROM expected
LEFT JOIN import_batches AS batch ON batch.batch_id = expected.batch_id
LEFT JOIN jobs AS job ON job.job_id = expected.job_id
LEFT JOIN artifact_manifests AS artifact
  ON artifact.artifact_id = expected.artifact_id
 AND artifact.batch_id = expected.batch_id
 AND artifact.job_id = expected.job_id
LEFT JOIN import_projection_finalize_receipts AS receipt
  ON receipt.batch_id = expected.batch_id
 AND receipt.job_id = expected.job_id
 AND receipt.artifact_id = expected.artifact_id
""".strip()

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BATCH_ID_RE = re.compile(r"^api-batch:[0-9a-f]{64}$")
JOB_ID_RE = re.compile(r"^api-job:[0-9a-f]{64}$")
ARTIFACT_ID_RE = re.compile(r"^artifact-[0-9a-f]{64}$")
ARTIFACT_KEY_RE = re.compile(
    r"^imports/v1/[0-9]{4}/[0-9]{2}/[0-9]{2}/[0-9a-f]{64}\.json$"
)
CommandFunc = Callable[[argparse.Namespace], int]


class PreviewCanaryError(RuntimeError):
    """Preview canary validation failed closed."""


@dataclass(frozen=True)
class ObjectReceipt:
    bytes: int
    sha256: str


@dataclass(frozen=True)
class PreviewCanaryPayload:
    commit: str
    commit_time: str
    event_id: str
    idempotency_key: str
    events: list[dict[str, Any]]


def _print_json(value: Any) -> None:  # noqa: ANN401
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _read_json(path: Path) -> Any:  # noqa: ANN401
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:  # noqa: ANN401
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _int_value(value: Any) -> int | None:  # noqa: ANN401
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _validate_commit(commit: str) -> str:
    candidate = commit.strip().lower()
    if not COMMIT_RE.fullmatch(candidate):
        raise PreviewCanaryError("commit_invalid")
    return candidate


def _validate_batch_id(batch_id: str) -> str:
    candidate = batch_id.strip()
    if not BATCH_ID_RE.fullmatch(candidate):
        raise PreviewCanaryError("batch_id_invalid")
    return candidate


def _validate_job_id(job_id: str) -> str:
    candidate = job_id.strip()
    if not JOB_ID_RE.fullmatch(candidate):
        raise PreviewCanaryError("job_id_invalid")
    return candidate


def _validate_artifact_id(artifact_id: str) -> str:
    candidate = artifact_id.strip()
    if not ARTIFACT_ID_RE.fullmatch(candidate):
        raise PreviewCanaryError("artifact_id_invalid")
    return candidate


def _validate_sha256(value: Any, blocker: str, blockers: list[str]) -> str | None:  # noqa: ANN401
    if isinstance(value, str) and SHA256_RE.fullmatch(value):
        return value
    blockers.append(blocker)
    return None


def _validate_artifact_key(value: Any, blockers: list[str]) -> str | None:  # noqa: ANN401
    if isinstance(value, str) and ARTIFACT_KEY_RE.fullmatch(value):
        return value
    blockers.append("artifact_key_invalid")
    return None


def build_canary_payload(*, commit: str, commit_time: str) -> PreviewCanaryPayload:
    normalized_commit = _validate_commit(commit)
    event_id = f"preview-artifact-canary-{normalized_commit[:12]}"
    return PreviewCanaryPayload(
        commit=normalized_commit,
        commit_time=commit_time,
        event_id=event_id,
        idempotency_key=f"preview-artifact-canary:{normalized_commit}",
        events=[
            {
                "collected_at": commit_time,
                "content_original": "Deterministic Cloudflare preview artifact canary.",
                "event_id": event_id,
                "language": "en",
                "pipeline_stage": "collected",
                "source_id": "preview-canary-synthetic-source",
                "summary": "Synthetic event used to verify preview durable import receipts.",
                "target_id": "preview-canary",
                "title_original": f"News Sentry Preview Artifact Canary {normalized_commit[:12]}",
                "url": f"https://example.test/news-sentry/{event_id}",
            }
        ],
    )


def build_evidence_sql(*, batch_id: str, job_id: str, artifact_id: str) -> str:
    batch = _validate_batch_id(batch_id)
    job = _validate_job_id(job_id)
    artifact = _validate_artifact_id(artifact_id)
    return (
        EVIDENCE_SQL_TEMPLATE.replace("__BATCH_ID__", batch)
        .replace("__JOB_ID__", job)
        .replace("__ARTIFACT_ID__", artifact)
    )


def object_receipt(path: Path) -> ObjectReceipt:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
    return ObjectReceipt(bytes=total, sha256=digest.hexdigest())


def _response_identity(
    response: Mapping[str, Any],
    label: str,
    blockers: list[str],
) -> dict[str, Any]:
    batch_id = response.get("batch_id")
    job_id = response.get("job_id")
    artifact_id = response.get("artifact_id")
    artifact_key = response.get("artifact_key")
    artifact_sha256 = response.get("artifact_sha256")
    artifact_bytes = _int_value(response.get("artifact_bytes"))
    errors = response.get("errors")
    if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
        blockers.append(f"{label}_batch_id_invalid")
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        blockers.append(f"{label}_job_id_invalid")
    if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(artifact_id):
        blockers.append(f"{label}_artifact_id_invalid")
    if not isinstance(artifact_key, str) or not ARTIFACT_KEY_RE.fullmatch(artifact_key):
        blockers.append(f"{label}_artifact_key_invalid")
    _validate_sha256(artifact_sha256, f"{label}_artifact_sha256_invalid", blockers)
    if artifact_bytes is None or artifact_bytes < 0:
        blockers.append(f"{label}_artifact_bytes_invalid")
    if errors != []:
        blockers.append(f"{label}_errors_nonempty")
    return {
        "batch_id": batch_id,
        "job_id": job_id,
        "artifact_id": artifact_id,
        "artifact_key": artifact_key,
        "artifact_sha256": artifact_sha256,
        "artifact_bytes": artifact_bytes,
        "replayed": response.get("replayed"),
    }


def _same_identity(
    first: Mapping[str, Any],
    replay: Mapping[str, Any],
    field: str,
    blockers: list[str],
) -> None:
    if first.get(field) != replay.get(field):
        blockers.append(f"response_{field}_mismatch")


def _count(row: Mapping[str, Any], key: str, blockers: list[str]) -> int | None:
    parsed = _int_value(row.get(key))
    if parsed is None:
        blockers.append(f"{key}_missing")
    elif parsed != 1:
        blockers.append(f"{key}_invalid")
    return parsed


def _failed_receipt(blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "blockers": sorted(dict.fromkeys(blockers)),
    }


def build_canary_receipt(
    *,
    first_response: Mapping[str, Any],
    replay_response: Mapping[str, Any],
    d1_rows: list[dict[str, Any]],
    artifact_path: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    first = _response_identity(first_response, "first_response", blockers)
    replay = _response_identity(replay_response, "replay_response", blockers)
    for field in (
        "batch_id",
        "job_id",
        "artifact_id",
        "artifact_key",
        "artifact_sha256",
        "artifact_bytes",
    ):
        _same_identity(first, replay, field, blockers)
    if first.get("replayed") is not False:
        blockers.append("first_response_replayed_invalid")
    if replay.get("replayed") is not True:
        blockers.append("replay_response_replayed_invalid")

    if len(d1_rows) != 1:
        blockers.append("d1_row_count_invalid")
        return _failed_receipt(blockers)
    row = d1_rows[0]

    batch_count = _count(row, "batch_count", blockers)
    job_count = _count(row, "job_count", blockers)
    artifact_count = _count(row, "artifact_count", blockers)
    projection_count = _count(row, "projection_receipt_count", blockers)
    event_count = _count(row, "event_count", blockers)

    for status_key in ("batch_status", "job_status", "artifact_status"):
        if row.get(status_key) != "committed":
            blockers.append(f"{status_key}_invalid")
    for row_key, response_key in (
        ("batch_id", "batch_id"),
        ("job_id", "job_id"),
        ("artifact_id", "artifact_id"),
        ("artifact_batch_id", "batch_id"),
        ("artifact_job_id", "job_id"),
        ("artifact_key", "artifact_key"),
        ("artifact_sha256", "artifact_sha256"),
        ("artifact_bytes", "artifact_bytes"),
    ):
        if row.get(row_key) != first.get(response_key):
            blockers.append(f"{row_key}_mismatch")

    if row.get("projection_batch_guard") != row.get("batch_id"):
        blockers.append("projection_batch_guard_mismatch")
    if row.get("projection_job_guard") != row.get("job_id"):
        blockers.append("projection_job_guard_mismatch")
    if row.get("projection_artifact_guard") != row.get("artifact_id"):
        blockers.append("projection_artifact_guard_mismatch")
    batch_checksum = _validate_sha256(
        row.get("batch_checksum"), "batch_checksum_invalid", blockers
    )
    if row.get("projection_batch_checksum") != batch_checksum:
        blockers.append("projection_batch_checksum_mismatch")

    key = _validate_artifact_key(row.get("artifact_key"), blockers)
    sha256 = _validate_sha256(row.get("artifact_sha256"), "artifact_sha256_invalid", blockers)
    expected_bytes = _int_value(row.get("artifact_bytes"))
    if expected_bytes is None or expected_bytes < 0:
        blockers.append("artifact_bytes_invalid")
    file_receipt = object_receipt(artifact_path)
    if sha256 and file_receipt.sha256 != sha256:
        blockers.append("artifact_sha256_mismatch")
    if expected_bytes is not None and file_receipt.bytes != expected_bytes:
        blockers.append("artifact_bytes_mismatch")
    if key and sha256 and Path(key).stem != sha256:
        blockers.append("artifact_key_sha_mismatch")

    if blockers:
        return _failed_receipt(blockers)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "identity": {
            "batch_id": first["batch_id"],
            "job_id": first["job_id"],
            "artifact_id": first["artifact_id"],
        },
        "artifact": {
            "bytes": file_receipt.bytes,
            "key": key,
            "sha256": file_receipt.sha256,
            "status": row["artifact_status"],
        },
        "counts": {
            "artifact": artifact_count,
            "batch": batch_count,
            "event": event_count,
            "job": job_count,
            "projection_receipt": projection_count,
        },
        "responses": {
            "first": {"status": "committed", "replayed": first["replayed"]},
            "replay": {"status": "committed", "replayed": replay["replayed"]},
        },
    }


def parse_wrangler_d1_json(value: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    payload = value
    if isinstance(payload, str):
        text = payload.strip()
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                payload, _ = decoder.raw_decode(text[index:])
                break
            except json.JSONDecodeError:
                continue
        else:
            raise PreviewCanaryError("wrangler_json_missing")
    candidates = payload if isinstance(payload, list) else [payload]
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        rows = candidate.get("results")
        if rows is None:
            rows = candidate.get("result")
        if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
            return list(rows)
    if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
        return list(payload)
    raise PreviewCanaryError("wrangler_results_missing")


def _payload_command(args: argparse.Namespace) -> int:
    payload = build_canary_payload(commit=args.commit, commit_time=args.commit_time)
    rendered = {"api_url": PREVIEW_IMPORT_URL, **asdict(payload)}
    if args.output:
        _write_json(args.output, rendered)
    _print_json(rendered)
    return 0


def _evidence_sql_command(args: argparse.Namespace) -> int:
    print(
        build_evidence_sql(
            batch_id=args.batch_id,
            job_id=args.job_id,
            artifact_id=args.artifact_id,
        )
    )
    return 0


def _receipt_command(args: argparse.Namespace) -> int:
    try:
        d1_rows = parse_wrangler_d1_json(args.d1_json.read_text(encoding="utf-8"))
        receipt = build_canary_receipt(
            first_response=_read_json(args.first_response),
            replay_response=_read_json(args.replay_response),
            d1_rows=d1_rows,
            artifact_path=args.artifact,
        )
    except (OSError, json.JSONDecodeError, PreviewCanaryError) as error:
        receipt = _failed_receipt([str(error)])
    if args.output:
        _write_json(args.output, receipt)
    _print_json(receipt)
    return 0 if receipt["status"] == "ok" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    payload = subparsers.add_parser("payload")
    payload.add_argument("--commit", required=True)
    payload.add_argument("--commit-time", required=True)
    payload.add_argument("--output", type=Path)
    payload.set_defaults(func=_payload_command)

    sql = subparsers.add_parser("evidence-sql")
    sql.add_argument("--batch-id", required=True)
    sql.add_argument("--job-id", required=True)
    sql.add_argument("--artifact-id", required=True)
    sql.set_defaults(func=_evidence_sql_command)

    receipt = subparsers.add_parser("receipt")
    receipt.add_argument("--first-response", required=True, type=Path)
    receipt.add_argument("--replay-response", required=True, type=Path)
    receipt.add_argument("--d1-json", required=True, type=Path)
    receipt.add_argument("--artifact", required=True, type=Path)
    receipt.add_argument("--output", type=Path)
    receipt.set_defaults(func=_receipt_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command = cast(CommandFunc, args.func)
        return command(args)
    except PreviewCanaryError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
