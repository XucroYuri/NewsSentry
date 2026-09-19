from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.control_common import ControlError

from tools import isolation_proof as proof

SENTINEL = "iso-sentinel-preview-abc123"
OBSERVED_AT = "2026-09-19T12:00:00Z"


def _rows(*event_ids: str) -> list[dict[str, object]]:
    return [{"event_id": event_id} for event_id in event_ids]


def _write_rows(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps([{"results": rows}]), encoding="utf-8")
    return path


# ── 哨兵生成 ──────────────────────────────────────────────────────────────


def test_make_sentinel_is_deterministic_and_prefixed() -> None:
    first = proof.make_sentinel_id(target_id="preview", nonce="run-1")
    second = proof.make_sentinel_id(target_id="preview", nonce="run-1")
    other = proof.make_sentinel_id(target_id="preview", nonce="run-2")

    assert first == second
    assert first != other
    assert first.startswith(proof.SENTINEL_PREFIX)
    assert "preview" in first


def test_make_sentinel_rejects_empty_inputs() -> None:
    with pytest.raises(ControlError):
        proof.make_sentinel_id(target_id="  ", nonce="run-1")
    with pytest.raises(ControlError):
        proof.make_sentinel_id(target_id="preview", nonce="")


# ── SQL 生成 ──────────────────────────────────────────────────────────────


def test_sentinel_sql_is_idempotent_and_escapes() -> None:
    statement = proof.build_sentinel_sql(
        sentinel_id=SENTINEL,
        target_id="preview",
        source_id="isolation-sentinel",
        observed_at=OBSERVED_AT,
    )

    assert SENTINEL in statement
    assert "ON CONFLICT(event_id) DO NOTHING" in statement
    # events 表的四个 NOT NULL 列必须出现
    for column in ("event_id", "target_id", "source_id", "published_at", "collected_at", "title"):
        assert column in statement

    escaped = proof.build_sentinel_sql(
        sentinel_id=SENTINEL,
        target_id="o'brien",
        source_id="s",
        observed_at=OBSERVED_AT,
    )
    assert "'o''brien'" in escaped


def test_sentinel_sql_rejects_unprefixed_or_empty_values() -> None:
    with pytest.raises(ControlError):
        proof.build_sentinel_sql(
            sentinel_id="not-a-sentinel",
            target_id="preview",
            source_id="s",
            observed_at=OBSERVED_AT,
        )
    with pytest.raises(ControlError):
        proof.build_sentinel_sql(
            sentinel_id=SENTINEL, target_id=" ", source_id="s", observed_at=OBSERVED_AT
        )
    with pytest.raises(ControlError):
        proof.build_sentinel_sql(
            sentinel_id=SENTINEL, target_id="preview", source_id="s", observed_at=""
        )


# ── 隔离验证：阳性对照 + 双方非空 ─────────────────────────────────────────


def test_verify_passes_when_sentinel_only_in_written_track() -> None:
    result = proof.verify_isolation(
        sentinel_id=SENTINEL,
        written_to="treatment",
        control_rows=_rows("ne-1", "ne-2"),
        treatment_rows=_rows("ne-1", SENTINEL),
    )

    assert result["verdict"] == "PASS"
    assert result["failures"] == []
    assert dict(result["checks"])["positive_control_sentinel_present"] is True


def test_verify_fails_when_sentinel_leaks_to_other_track() -> None:
    result = proof.verify_isolation(
        sentinel_id=SENTINEL,
        written_to="treatment",
        control_rows=_rows("ne-1", SENTINEL),  # 跨轨泄漏
        treatment_rows=_rows("ne-1", SENTINEL),
    )

    assert result["verdict"] == "FAIL"
    assert any("隔离失败" in failure for failure in result["failures"])


def test_verify_fails_without_positive_control() -> None:
    """哨兵没写进去时，"对照组里也没有"不构成任何证据。"""
    result = proof.verify_isolation(
        sentinel_id=SENTINEL,
        written_to="treatment",
        control_rows=_rows("ne-1", "ne-2"),
        treatment_rows=_rows("ne-1", "ne-2"),
    )

    assert result["verdict"] == "FAIL"
    assert any("阳性对照失败" in failure for failure in result["failures"])


@pytest.mark.parametrize(
    ("control", "treatment"),
    [
        ([], ["ne-1", SENTINEL]),  # 对照组结果集为空 → 无法判定
        (["ne-1"], []),  # 写入轨结果集为空 → 无法判定
        ([], []),
    ],
)
def test_verify_fails_closed_on_empty_result_sets(
    control: list[str], treatment: list[str]
) -> None:
    result = proof.verify_isolation(
        sentinel_id=SENTINEL,
        written_to="treatment",
        control_rows=_rows(*control),
        treatment_rows=_rows(*treatment),
    )

    assert result["verdict"] == "FAIL"
    assert any("无法判定" in failure for failure in result["failures"])


def test_verify_rejects_unprefixed_sentinel_and_bad_track() -> None:
    with pytest.raises(ControlError):
        proof.verify_isolation(
            sentinel_id="bogus",
            written_to="treatment",
            control_rows=_rows("ne-1"),
            treatment_rows=_rows("ne-1"),
        )
    with pytest.raises(ControlError):
        proof.verify_isolation(
            sentinel_id=SENTINEL,
            written_to="neither",
            control_rows=_rows("ne-1"),
            treatment_rows=_rows("ne-1"),
        )


# ── CLI ───────────────────────────────────────────────────────────────────


def test_cli_end_to_end(tmp_path: Path) -> None:
    sql_out = tmp_path / "sentinel.sql"
    assert (
        proof.main(
            [
                "sentinel-sql",
                "--sentinel", SENTINEL,
                "--target", "preview",
                "--observed-at", OBSERVED_AT,
                "--output", str(sql_out),
            ]
        )
        == 0
    )
    assert SENTINEL in sql_out.read_text(encoding="utf-8")

    control = _write_rows(tmp_path / "c.json", _rows("ne-1"))
    treatment = _write_rows(tmp_path / "t.json", _rows("ne-1", SENTINEL))

    assert (
        proof.main(
            [
                "verify",
                "--sentinel", SENTINEL,
                "--written-to", "treatment",
                "--control-events", str(control),
                "--treatment-events", str(treatment),
            ]
        )
        == 0
    )

    leaked = _write_rows(tmp_path / "leak.json", _rows("ne-1", SENTINEL))
    assert (
        proof.main(
            [
                "verify",
                "--sentinel", SENTINEL,
                "--written-to", "treatment",
                "--control-events", str(leaked),
                "--treatment-events", str(treatment),
            ]
        )
        == 1
    )


def test_cli_make_sentinel_prints_id(tmp_path: Path) -> None:
    assert proof.main(["make-sentinel", "--target", "preview", "--nonce", "n1"]) == 0
