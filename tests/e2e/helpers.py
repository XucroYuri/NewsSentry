"""Shared helpers for E2E tests — assertions, payload factories, etc."""

from __future__ import annotations

from typing import Any


def assert_ok(resp_data: dict[str, Any], *, expect_status: str = "ok") -> None:
    """Assert a response dictionary contains ``{"status": "ok"}`` (default)."""
    assert resp_data.get("status") == expect_status, (
        f"Expected status={expect_status!r}, got {resp_data!r}"
    )


def assert_auth_error(resp_data: dict[str, Any]) -> None:
    """Assert the response body is a valid Auth error."""
    assert "detail" in resp_data, f"Expected auth error detail, got {resp_data!r}"


def assert_validation_error(resp_data: dict[str, Any]) -> None:
    """Assert the response body is a Pydantic validation error (422 shape)."""
    assert resp_data.get("detail") is not None
    assert "validation_errors" in resp_data, f"Expected validation_errors key, got {resp_data!r}"
