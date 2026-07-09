"""Anonymous voting system for public news — Phase 2 of HN-style upgrade.

Implements HN-style upvote functionality without user accounts:
* ``voter_hash`` = sha256(client_ip + user_agent + daily_salt) for 24h dedup.
* Rate limit: max 50 votes per voter_hash per rolling 24h window.
* Storage: separate ``votes.db`` SQLite file in data_dir (decoupled from
  AsyncStore's async API to keep vote operations synchronous and simple).

Security notes:
* voter_hash is intentionally NOT reversible — it exists only for dedup, not
  for tracking. The daily salt rotates every 24h so hashes cannot be
  correlated across days.
* Rate limiting is per-hashed-identity, not per-IP, to handle NAT/shared IPs.
* Vote counts are eventually consistent — the list handler batch-queries
  counts per page load, and votes don't need to appear instantly.

See docs/upgrades/hacker-news-style-upgrade-plan.md §Phase 2.
"""

# ruff: noqa: S608
# All SQL in this module uses parameterized queries with pure "?" placeholders.
# The S608 rule flags any dynamic string construction in SQL, but the dynamic
# parts here are only placeholder character counts (e.g. "?,?,?"), never user
# input. The file-level suppression avoids per-line false positives.

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_RATE_LIMIT_VOTES",
    "DEFAULT_RATE_LIMIT_WINDOW_HOURS",
    "compute_voter_hash",
    "init_votes_db",
    "record_vote",
    "remove_vote",
    "has_voted",
    "get_vote_count",
    "get_vote_counts_batch",
    "check_rate_limit",
]

DEFAULT_RATE_LIMIT_VOTES = 50
DEFAULT_RATE_LIMIT_WINDOW_HOURS = 24

_VOTES_DB_FILENAME = "votes.db"
_DDL_NEWS_VOTES = """
CREATE TABLE IF NOT EXISTS news_votes (
    event_id   TEXT NOT NULL,
    voter_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (event_id, voter_hash)
)
"""

_DDL_VOTE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_news_votes_voter_time
ON news_votes(voter_hash, created_at DESC)
"""

_DDL_VOTE_COUNT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_news_votes_event
ON news_votes(event_id)
"""

# Module-level lock for write operations. SQLite handles concurrency at the
# DB level via WAL, but we also serialize Python-side to prevent "database is
# locked" errors under burst load.
_write_lock = threading.Lock()


def _votes_db_path(data_dir: Path) -> Path:
    return data_dir / _VOTES_DB_FILENAME


def _connect(data_dir: Path, *, timeout: float = 2.0) -> sqlite3.Connection:
    db_path = _votes_db_path(data_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{db_path}?mode=rwc"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_votes_db(data_dir: Path) -> None:
    """Create the votes table and indexes if they don't exist. Idempotent."""
    with _connect(data_dir) as conn:
        conn.execute(_DDL_NEWS_VOTES)
        conn.execute(_DDL_VOTE_INDEX)
        conn.execute(_DDL_VOTE_COUNT_INDEX)
        conn.commit()


def compute_voter_hash(
    client_ip: str | None,
    user_agent: str | None,
    *,
    salt: str | None = None,
    now: datetime | None = None,
) -> str:
    """Compute a non-reversible voter hash for dedup.

    The hash combines IP + User-Agent + a daily salt so that:
    * Same IP+UA within the same day → same hash (dedup works).
    * Same IP+UA across days → different hash (no cross-day correlation).
    * Different IP or UA → different hash (prevents simple ballot stuffing
      from one client, though it's not a strong identity guarantee).

    ``salt`` overrides the daily salt (useful for testing).
    """
    current = now or datetime.now(UTC)
    daily_salt = salt or current.strftime("%Y-%m-%d")
    raw = f"{client_ip or 'unknown'}|{user_agent or 'unknown'}|{daily_salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_vote(
    data_dir: Path,
    event_id: str,
    voter_hash: str,
    *,
    max_votes: int = DEFAULT_RATE_LIMIT_VOTES,
    window_hours: int = DEFAULT_RATE_LIMIT_WINDOW_HOURS,
    now: float | None = None,
) -> bool:
    """Record an upvote. Returns True if the vote was newly recorded.

    Returns False if:
    * The voter already voted on this event (idempotent — not an error).
    * The voter exceeded the rate limit for the rolling window.
    """
    init_votes_db(data_dir)
    current_ts = now if now is not None else time.time()
    cutoff = current_ts - window_hours * 3600

    with _write_lock:
        with _connect(data_dir) as conn:
            # Check rate limit: count votes by this voter in the window.
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM news_votes "
                "WHERE voter_hash = ? AND created_at >= ?",
                (voter_hash, cutoff),
            )
            row = cursor.fetchone()
            recent_count = int(row["cnt"]) if row else 0
            if recent_count >= max_votes:
                logger.info(
                    "Rate limit hit for voter_hash=%s... (%d/%d votes in %dh)",
                    voter_hash[:8],
                    recent_count,
                    max_votes,
                    window_hours,
                )
                return False

            # Insert (idempotent via PRIMARY KEY — returns 0 rows if exists).
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO news_votes (event_id, voter_hash, created_at) "
                    "VALUES (?, ?, ?)",
                    (event_id, voter_hash, current_ts),
                )
                conn.commit()
                cursor = conn.execute(
                    "SELECT changes() as changed"
                )
                return int(cursor.fetchone()["changed"]) > 0
            except sqlite3.IntegrityError:
                # Already voted — idempotent.
                return False


def remove_vote(data_dir: Path, event_id: str, voter_hash: str) -> bool:
    """Remove a previously recorded vote. Returns True if a vote was removed."""
    init_votes_db(data_dir)
    with _write_lock:
        with _connect(data_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM news_votes WHERE event_id = ? AND voter_hash = ?",
                (event_id, voter_hash),
            )
            conn.commit()
            return cursor.rowcount > 0


def has_voted(data_dir: Path, event_id: str, voter_hash: str) -> bool:
    """Check if a specific voter has voted on a specific event."""
    init_votes_db(data_dir)
    with _connect(data_dir) as conn:
        cursor = conn.execute(
            "SELECT 1 FROM news_votes WHERE event_id = ? AND voter_hash = ? LIMIT 1",
            (event_id, voter_hash),
        )
        return cursor.fetchone() is not None


def get_vote_count(data_dir: Path, event_id: str) -> int:
    """Get the total vote count for a single event."""
    init_votes_db(data_dir)
    with _connect(data_dir) as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM news_votes WHERE event_id = ?",
            (event_id,),
        )
        row = cursor.fetchone()
        return int(row["cnt"]) if row else 0


def get_vote_counts_batch(data_dir: Path, event_ids: list[str]) -> dict[str, int]:
    """Batch-query vote counts for multiple events.

    Returns a dict mapping event_id → vote_count. Events with no votes
    are included with count 0.
    """
    if not event_ids:
        return {}
    init_votes_db(data_dir)
    # SQLite parameter limit is typically 999; chunk large batches.
    chunk_size = 500
    result: dict[str, int] = dict.fromkeys(event_ids, 0)
    with _connect(data_dir) as conn:
        for i in range(0, len(event_ids), chunk_size):
            chunk = event_ids[i : i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            # Safe: placeholders are pure "?" chars, no user input.
            query = (
                "SELECT event_id, COUNT(*) as cnt FROM news_votes"
                + " WHERE event_id IN (" + placeholders + ") GROUP BY event_id"  # noqa: S608
            )
            cursor = conn.execute(query, chunk)
            for row in cursor:
                result[row["event_id"]] = int(row["cnt"])
    return result


def check_rate_limit(
    data_dir: Path,
    voter_hash: str,
    *,
    max_votes: int = DEFAULT_RATE_LIMIT_VOTES,
    window_hours: int = DEFAULT_RATE_LIMIT_WINDOW_HOURS,
    now: float | None = None,
) -> bool:
    """Check if the voter is within the rate limit. Returns True if allowed."""
    init_votes_db(data_dir)
    current_ts = now if now is not None else time.time()
    cutoff = current_ts - window_hours * 3600
    with _connect(data_dir) as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM news_votes "
            "WHERE voter_hash = ? AND created_at >= ?",
            (voter_hash, cutoff),
        )
        row = cursor.fetchone()
        recent_count = int(row["cnt"]) if row else 0
        return recent_count < max_votes


def extract_client_ip(request: Any) -> str | None:
    """Extract the best available client IP from a FastAPI Request."""
    headers = request.headers if hasattr(request, "headers") else {}
    cloudflare_ip: Any = headers.get("cf-connecting-ip")
    if cloudflare_ip:
        return str(cloudflare_ip).strip() or None
    real_ip: Any = headers.get("x-real-ip")
    if real_ip:
        return str(real_ip).strip() or None
    if hasattr(request, "client") and request.client:
        host: Any = request.client.host
        return str(host) if host else None
    forwarded: Any = headers.get("x-forwarded-for")
    if forwarded:
        # Fallback only. Production should sanitize proxy headers at the edge.
        return str(forwarded).split(",")[0].strip() or None
    return None


def extract_user_agent(request: Any) -> str | None:
    """Extract the User-Agent header from a FastAPI Request."""
    if hasattr(request, "headers"):
        ua: Any = request.headers.get("user-agent")
        return str(ua) if ua else None
    return None
