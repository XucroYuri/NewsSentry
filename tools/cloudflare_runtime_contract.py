"""Shared typed constants for Cloudflare runtime migrations and receipts."""

from __future__ import annotations

EXPECTED_MIGRATION_RECEIPTS: tuple[str, ...] = (
    "20260801_phase0_data_quarantine",
    "20260801_phase1_job_runtime",
    "20260802_phase2_import_staging",
    "20260802_phase2_dlq_replay_receipts",
    "20260802_phase3_durable_artifacts",
    "20260802_phase4_projection_import",
    "20260802_phase5_future_event_quarantine",
)
