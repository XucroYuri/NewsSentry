"""Phase 5: Events & Data Flow API E2E tests — requires authentication.

Covers event listing/filtering, event detail, feed, import, transition,
stats, trends, chains, feedback, and alerts.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e

_TEST_TARGET = "e2e-test-target"


# ── Events ────────────────────────────────────────────────────────────────


class TestEvents:
    def test_list_events_empty(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/events",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data
        assert data["total"] == 0

    def test_list_events_pagination(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/events",
            params={"target_id": _TEST_TARGET, "page": 1, "page_size": 5},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_list_events_with_classification_filter(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/events",
            params={"target_id": _TEST_TARGET, "classification": "international-relations"},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_list_events_with_search(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/events",
            params={"target_id": _TEST_TARGET, "search": "test"},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_get_nonexistent_event_returns_404(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/events/ne-nonexistent-00000000",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 404

    def test_events_feed(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/events/feed",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("groups", []), list)


# ── Import Events ─────────────────────────────────────────────────────────


class TestImportEvents:
    def test_import_events(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.post(
            "/api/v1/events/import",
            json=[
                {
                    "event_id": "ne-e2e-import-0001",
                    "target_id": _TEST_TARGET,
                    "source_id": "e2e-test-source",
                    "title_original": "E2E Import Test Event",
                    "url": "https://example.com/e2e/import/001",
                    "published_at": "2026-06-01T00:00:00Z",
                    "collected_at": "2026-06-01T00:00:00Z",
                    "language": "en",
                    "content_original": "E2E import content.",
                    "news_value_score": 75,
                    "china_relevance": 50,
                },
                {
                    "event_id": "ne-e2e-import-0002",
                    "target_id": _TEST_TARGET,
                    "source_id": "e2e-test-source",
                    "title_original": "E2E Import Test Event 2",
                    "url": "https://example.com/e2e/import/002",
                    "published_at": "2026-06-02T00:00:00Z",
                    "collected_at": "2026-06-02T00:00:00Z",
                    "language": "en",
                    "content_original": "E2E import content 2.",
                    "news_value_score": 80,
                    "china_relevance": 60,
                },
            ],
            headers=auth_header,
        )
        assert resp.status_code == 200, f"Import failed: {resp.text}"
        data = resp.json()
        # Should report imported count
        assert data["imported"] >= 1

    def test_imported_events_are_listable(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/events",
            params={"target_id": _TEST_TARGET, "search": "E2E Import"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

    def test_import_duplicate_skipped(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/events/import",
            json=[
                {
                    "event_id": "ne-e2e-import-0001",
                    "target_id": _TEST_TARGET,
                    "source_id": "e2e-test-source",
                    "title_original": "Duplicate event",
                    "url": "https://example.com/e2e/import/001",
                    "published_at": "2026-06-01T00:00:00Z",
                    "collected_at": "2026-06-01T00:00:00Z",
                    "language": "en",
                }
            ],
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("skipped", 0) >= 1


# ── Event Transition ──────────────────────────────────────────────────────


class TestEventTransition:
    def test_transition_to_reviewed(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/admin/events/ne-e2e-import-0001/transition",
            json={
                "target_id": _TEST_TARGET,
                "to_stage": "reviewed",
                "reason": "E2E test review",
            },
            headers=auth_header,
        )
        assert resp.status_code == 200, f"Transition failed: {resp.text}"

    def test_transition_to_published(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/admin/events/ne-e2e-import-0002/transition",
            json={
                "target_id": _TEST_TARGET,
                "to_stage": "published",
                "reason": "E2E test publish",
            },
            headers=auth_header,
        )
        assert resp.status_code == 200


# ── Stats ─────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/stats",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == _TEST_TARGET
        assert data["total_events"] >= 0

    def test_today_stats(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/stats/today",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_top_events(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/events/top",
            params={"target_id": _TEST_TARGET, "days": 7, "limit": 5},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data


# ── Trends ────────────────────────────────────────────────────────────────


class TestTrends:
    def test_topic_trends(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/trends/topics",
            params={"target_id": _TEST_TARGET, "days": 14},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == _TEST_TARGET

    def test_sentiment_trends(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/trends/sentiment",
            params={"target_id": _TEST_TARGET, "days": 14},
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_sentiment" in data


# ── Chains ────────────────────────────────────────────────────────────────


class TestChains:
    def test_list_chains(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/chains",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200


# ── Feedback ──────────────────────────────────────────────────────────────


class TestFeedback:
    def test_submit_feedback(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/feedback",
            json={
                "target_id": _TEST_TARGET,
                "event_id": "ne-e2e-import-0001",
                "verdict_type": "publish_override",
                "comment": "E2E test feedback",
            },
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == "ne-e2e-import-0001"

    def test_list_feedback(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/feedback",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_feedback_stats(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/feedback/stats",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200


# ── Alerts ────────────────────────────────────────────────────────────────


class TestAlerts:
    def test_smart_alerts(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/alerts/smart",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_alert_history(self, e2e_client: httpx.Client, auth_header: dict) -> None:
        resp = e2e_client.get(
            "/api/v1/alerts/history",
            params={"target_id": _TEST_TARGET},
            headers=auth_header,
        )
        assert resp.status_code == 200
