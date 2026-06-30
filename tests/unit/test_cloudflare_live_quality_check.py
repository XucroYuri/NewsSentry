"""Cloudflare live quality gate tests."""

from __future__ import annotations

from tools.cloudflare_live_quality_check import QualityThresholds, evaluate_receipt


def _healthy_receipt() -> dict[str, object]:
    return {
        "health": {
            "status": "ok",
            "total_events": 10848,
            "latest_collected_at": "2026-06-28T07:09:40Z",
            "public_quality": {
                "summary_ready": 750,
                "recommendation_ready": 750,
                "featured_total": 6426,
                "latest_public_at": "2026-06-28T07:09:40Z",
            },
        },
        "featured": {
            "http_status": 200,
            "total": 6426,
            "items": 3,
            "copy_ready": 3,
            "snapshot": "hit",
            "ttfb_ms": 250,
            "warm_ttfb_median_ms": 230,
            "warm_ttfb_p95_ms": 400,
        },
        "all": {
            "http_status": 200,
            "total": 10845,
            "items": 3,
            "snapshot": "hit",
            "ttfb_ms": 220,
            "warm_ttfb_median_ms": 210,
            "warm_ttfb_p95_ms": 360,
        },
        "bootstrap": {
            "http_status": 200,
            "total": 6426,
            "items": 20,
            "snapshot": "hit",
            "ttfb_ms": 300,
            "warm_ttfb_median_ms": 280,
            "warm_ttfb_p95_ms": 500,
        },
        "facets": {
            "http_status": 200,
            "regions": 12,
            "issues": 30,
            "related": 30,
            "snapshot": "hit",
            "ttfb_ms": 200,
            "warm_ttfb_median_ms": 190,
            "warm_ttfb_p95_ms": 350,
        },
        "d1_targets": {"http_status": 200, "count": 82},
        "head": {"http_status": 200},
        "write_guard": {"http_status": 403},
        "pages": {"http_status": 200, "js_contains_api_base": True},
        "generated_at": "2026-06-28T08:00:00Z",
    }


def test_evaluate_receipt_accepts_healthy_cloudflare_site() -> None:
    result = evaluate_receipt(
        _healthy_receipt(),
        QualityThresholds(min_featured=100, min_summary_ready=500, max_latest_age_hours=24),
    )

    assert result.ok is True
    assert result.failures == []


def test_evaluate_receipt_fails_for_translation_and_head_regressions() -> None:
    receipt = _healthy_receipt()
    receipt["health"]["public_quality"]["summary_ready"] = 7  # type: ignore[index]
    receipt["head"]["http_status"] = 404  # type: ignore[index]

    result = evaluate_receipt(
        receipt,
        QualityThresholds(min_featured=100, min_summary_ready=500, max_latest_age_hours=24),
    )

    assert result.ok is False
    assert "summary_ready_below_threshold" in result.failures
    assert "head_probe_failed" in result.failures


def test_evaluate_receipt_fails_when_snapshot_or_warm_ttfb_regresses() -> None:
    receipt = _healthy_receipt()
    receipt["featured"]["snapshot"] = "miss"  # type: ignore[index]
    receipt["all"]["snapshot"] = "miss"  # type: ignore[index]
    receipt["bootstrap"]["ttfb_ms"] = 901  # type: ignore[index]
    receipt["facets"]["snapshot"] = "bypass"  # type: ignore[index]

    result = evaluate_receipt(
        receipt,
        QualityThresholds(min_featured=100, min_summary_ready=500, max_latest_age_hours=24),
    )

    assert result.ok is False
    assert "featured_snapshot_not_hit" in result.failures
    assert "all_snapshot_not_hit" in result.failures
    assert "bootstrap_ttfb_above_threshold" in result.failures
    assert "facets_snapshot_not_hit" in result.failures


def test_evaluate_receipt_fails_when_featured_copy_or_targets_regress() -> None:
    receipt = _healthy_receipt()
    receipt["featured"]["copy_ready"] = 2  # type: ignore[index]
    receipt["d1_targets"]["count"] = 12  # type: ignore[index]

    result = evaluate_receipt(
        receipt,
        QualityThresholds(min_featured=100, min_summary_ready=500, min_d1_targets=80),
    )

    assert result.ok is False
    assert "featured_public_copy_missing" in result.failures
    assert "d1_targets_below_threshold" in result.failures
