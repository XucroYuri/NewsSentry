from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.deploy_receipt_metadata import ReceiptMetadataError, resolve_metadata

COMMIT = "a" * 40


def _receipt(**overrides: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "status": "ok",
        "environment": "production",
        "commit": COMMIT,
        "deployed_at": "2026-08-02T22:07:30Z",
        "worker_version": "version-1",
        "deployment_id": "deployment-1",
        "continuity": {
            "status": "ok",
            "latest_collect_updated_at": "2026-08-02T22:16:11Z",
            "selected_target_ids": ["japan"],
        },
    }
    receipt.update(overrides)
    return receipt


def test_resolve_metadata_returns_only_bounded_production_fields() -> None:
    metadata = resolve_metadata(_receipt(), expected_commit=COMMIT)

    assert metadata == {
        "environment": "production",
        "deployed_commit": COMMIT,
        "deployed_at": "2026-08-02T22:07:30Z",
        "worker_version": "version-1",
        "deployment_id": "deployment-1",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"status": "failed"}, "status is not ok"),
        ({"environment": "preview"}, "environment is not production"),
        ({"commit": "short"}, "commit is not a full SHA"),
        ({"deployed_at": "not-a-date"}, "deployed_at is invalid"),
        ({"worker_version": ""}, "worker_version is missing"),
        ({"deployment_id": None}, "deployment_id is missing"),
        ({"continuity": {"status": "failed"}}, "continuity is not ok"),
        (
            {
                "continuity": {
                    "status": "ok",
                    "latest_collect_updated_at": "2026-08-02T22:16:11Z",
                    "selected_target_ids": [],
                }
            },
            "selected targets are missing",
        ),
    ],
)
def test_resolve_metadata_rejects_incomplete_or_wrong_receipts(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ReceiptMetadataError, match=message):
        resolve_metadata(_receipt(**overrides), expected_commit=COMMIT)


def test_resolve_metadata_rejects_expected_commit_mismatch() -> None:
    with pytest.raises(ReceiptMetadataError, match="expected commit mismatch"):
        resolve_metadata(_receipt(), expected_commit="b" * 40)


def test_cli_writes_bounded_metadata(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    output_path = tmp_path / "metadata.json"
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    from tools.deploy_receipt_metadata import main

    assert main([
        "--receipt",
        str(receipt_path),
        "--expected-commit",
        COMMIT,
        "--output",
        str(output_path),
    ]) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["deployed_commit"] == COMMIT
