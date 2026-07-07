"""Tests for ``news_sentry.core.voting`` — anonymous HN-style upvote system.

Covers voter_hash computation, vote recording/dedup, rate limiting,
batch queries, and request field extraction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from news_sentry.core.voting import (
    DEFAULT_RATE_LIMIT_VOTES,
    check_rate_limit,
    compute_voter_hash,
    extract_client_ip,
    extract_user_agent,
    get_vote_count,
    get_vote_counts_batch,
    has_voted,
    init_votes_db,
    record_vote,
    remove_vote,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    init_votes_db(tmp_path)
    return tmp_path


class TestComputeVoterHash:
    def test_deterministic_same_inputs_same_day(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        a = compute_voter_hash("1.2.3.4", "Mozilla/5.0", now=now)
        b = compute_voter_hash("1.2.3.4", "Mozilla/5.0", now=now)
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_different_ip_different_hash(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        a = compute_voter_hash("1.2.3.4", "Mozilla/5.0", now=now)
        b = compute_voter_hash("5.6.7.8", "Mozilla/5.0", now=now)
        assert a != b

    def test_different_ua_different_hash(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        a = compute_voter_hash("1.2.3.4", "Mozilla/5.0", now=now)
        b = compute_voter_hash("1.2.3.4", "Chrome/120", now=now)
        assert a != b

    def test_different_day_different_hash(self) -> None:
        day1 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        day2 = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
        a = compute_voter_hash("1.2.3.4", "Mozilla/5.0", now=day1)
        b = compute_voter_hash("1.2.3.4", "Mozilla/5.0", now=day2)
        assert a != b

    def test_none_inputs_produce_valid_hash(self) -> None:
        now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
        h = compute_voter_hash(None, None, now=now)
        assert len(h) == 64

    def test_custom_salt_overrides_daily_rotation(self) -> None:
        day1 = datetime(2026, 7, 7, tzinfo=UTC)
        day2 = datetime(2026, 7, 8, tzinfo=UTC)
        a = compute_voter_hash("1.2.3.4", "UA", salt="fixed", now=day1)
        b = compute_voter_hash("1.2.3.4", "UA", salt="fixed", now=day2)
        assert a == b


class TestRecordVote:
    def test_new_vote_returns_true(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        assert record_vote(data_dir, "evt-1", vh) is True

    def test_duplicate_vote_returns_false(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        assert record_vote(data_dir, "evt-1", vh) is True
        assert record_vote(data_dir, "evt-1", vh) is False

    def test_different_voters_can_vote_same_event(self, data_dir: Path) -> None:
        vh1 = compute_voter_hash("1.2.3.4", "UA1")
        vh2 = compute_voter_hash("5.6.7.8", "UA2")
        assert record_vote(data_dir, "evt-1", vh1) is True
        assert record_vote(data_dir, "evt-1", vh2) is True

    def test_same_voter_can_vote_different_events(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        assert record_vote(data_dir, "evt-1", vh) is True
        assert record_vote(data_dir, "evt-2", vh) is True

    def test_rate_limit_blocks_after_max_votes(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        # Record max_votes successful votes on different events.
        for i in range(DEFAULT_RATE_LIMIT_VOTES):
            assert record_vote(data_dir, f"evt-{i}", vh) is True
        # Next vote should be rate-limited.
        assert record_vote(data_dir, "evt-blocked", vh) is False

    def test_rate_limit_window_expires(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        now = 1_000_000.0
        # Record votes at time T.
        for i in range(DEFAULT_RATE_LIMIT_VOTES):
            record_vote(data_dir, f"evt-old-{i}", vh, now=now)
        # After window expires, new votes should succeed.
        future = now + 25 * 3600  # 25h later
        assert record_vote(data_dir, "evt-new", vh, now=future) is True


class TestRemoveVote:
    def test_remove_existing_vote(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        record_vote(data_dir, "evt-1", vh)
        assert remove_vote(data_dir, "evt-1", vh) is True
        assert get_vote_count(data_dir, "evt-1") == 0

    def test_remove_nonexistent_vote_returns_false(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        assert remove_vote(data_dir, "evt-1", vh) is False

    def test_can_revote_after_removing(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        record_vote(data_dir, "evt-1", vh)
        remove_vote(data_dir, "evt-1", vh)
        assert record_vote(data_dir, "evt-1", vh) is True


class TestHasVoted:
    def test_returns_false_before_voting(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        assert has_voted(data_dir, "evt-1", vh) is False

    def test_returns_true_after_voting(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        record_vote(data_dir, "evt-1", vh)
        assert has_voted(data_dir, "evt-1", vh) is True

    def test_returns_false_after_removing(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        record_vote(data_dir, "evt-1", vh)
        remove_vote(data_dir, "evt-1", vh)
        assert has_voted(data_dir, "evt-1", vh) is False


class TestGetVoteCount:
    def test_zero_for_no_votes(self, data_dir: Path) -> None:
        assert get_vote_count(data_dir, "evt-1") == 0

    def test_counts_multiple_voters(self, data_dir: Path) -> None:
        for ip in ["1.1.1.1", "2.2.2.2", "3.3.3.3"]:
            vh = compute_voter_hash(ip, "UA")
            record_vote(data_dir, "evt-1", vh)
        assert get_vote_count(data_dir, "evt-1") == 3


class TestGetVoteCountsBatch:
    def test_empty_input(self, data_dir: Path) -> None:
        assert get_vote_counts_batch(data_dir, []) == {}

    def test_returns_zero_for_unvoted_events(self, data_dir: Path) -> None:
        result = get_vote_counts_batch(data_dir, ["evt-1", "evt-2"])
        assert result == {"evt-1": 0, "evt-2": 0}

    def test_returns_correct_counts(self, data_dir: Path) -> None:
        for ip in ["1.1.1.1", "2.2.2.2"]:
            record_vote(data_dir, "evt-1", compute_voter_hash(ip, "UA"))
        record_vote(data_dir, "evt-2", compute_voter_hash("3.3.3.3", "UA"))
        result = get_vote_counts_batch(data_dir, ["evt-1", "evt-2", "evt-3"])
        assert result["evt-1"] == 2
        assert result["evt-2"] == 1
        assert result["evt-3"] == 0


class TestCheckRateLimit:
    def test_returns_true_under_limit(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        assert check_rate_limit(data_dir, vh) is True

    def test_returns_false_at_limit(self, data_dir: Path) -> None:
        vh = compute_voter_hash("1.2.3.4", "UA")
        for i in range(DEFAULT_RATE_LIMIT_VOTES):
            record_vote(data_dir, f"evt-{i}", vh)
        assert check_rate_limit(data_dir, vh) is False


class TestExtractRequestFields:
    def test_extract_client_ip_prefers_cloudflare_header(self) -> None:
        class FakeClient:
            host = "9.9.9.9"
        class FakeRequest:
            headers = {
                "cf-connecting-ip": "1.2.3.4",
                "x-forwarded-for": "5.6.7.8",
            }
            client = FakeClient()
        assert extract_client_ip(FakeRequest()) == "1.2.3.4"

    def test_extract_client_ip_from_forwarded(self) -> None:
        class FakeRequest:
            headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
            client = None
        assert extract_client_ip(FakeRequest()) == "1.2.3.4"

    def test_extract_client_ip_from_client(self) -> None:
        class FakeClient:
            host = "9.9.9.9"
        class FakeRequest:
            headers = {}
            client = FakeClient()
        assert extract_client_ip(FakeRequest()) == "9.9.9.9"

    def test_extract_client_ip_none(self) -> None:
        class FakeRequest:
            headers = {}
            client = None
        assert extract_client_ip(FakeRequest()) is None

    def test_extract_user_agent(self) -> None:
        class FakeRequest:
            headers = {"user-agent": "Mozilla/5.0"}
        assert extract_user_agent(FakeRequest()) == "Mozilla/5.0"

    def test_extract_user_agent_missing(self) -> None:
        class FakeRequest:
            headers = {}
        assert extract_user_agent(FakeRequest()) is None


class TestInitVotesDb:
    def test_idempotent(self, tmp_path: Path) -> None:
        init_votes_db(tmp_path)
        init_votes_db(tmp_path)  # Should not raise
        assert get_vote_count(tmp_path, "evt-1") == 0
