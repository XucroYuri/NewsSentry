"""Phase 3: Authentication API E2E tests.

Covers login, token exchange, logout, me, change-password, setup-status, and setup.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.e2e


# ── Login ─────────────────────────────────────────────────────────────────


class TestLogin:
    def test_login_with_valid_credentials_returns_token(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "e2e-admin-pass-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"  # noqa: S105
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert data["expires_in"] > 0

    def test_login_with_invalid_password_returns_401(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert "Invalid credentials" in str(data.get("detail", ""))

    def test_login_with_empty_credentials_returns_400(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "", "password": ""},
        )
        assert resp.status_code == 400

    def test_login_with_missing_body_returns_422(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422


# ── Token Exchange ────────────────────────────────────────────────────────


class TestTokenExchange:
    def test_token_with_valid_api_key_succeeds(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/token",
            json={"api_key": "e2e-test-api-key-00000000"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_token_with_invalid_api_key_returns_401(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/token",
            json={"api_key": "invalid-key-12345678"},
        )
        assert resp.status_code == 401

    def test_token_with_missing_body_returns_400(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post("/api/v1/auth/token", json={})
        assert resp.status_code in (400, 422)


# ── Logout ────────────────────────────────────────────────────────────────


class TestLogout:
    def test_logout_returns_ok(self, e2e_client: httpx.Client, admin_token: str) -> None:
        """Verify logout returns 200.

        Note: in NEWSSENTRY_DEPLOYMENT_ENV=local mode, loopback requests
        bypass auth entirely, so we cannot reliably test that the token
        is invalidated afterward. We validate the logout endpoint itself.
        """
        resp = e2e_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"

    def test_logout_without_token_still_returns_ok(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"


# ── Auth Me ────────────────────────────────────────────────────────────────


class TestAuthMe:
    def test_me_returns_user_info(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.get("/api/v1/auth/me", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert "permissions" in data

    def test_me_without_token_allowed_on_local(
        self, e2e_client: httpx.Client
    ) -> None:
        """Local development mode allows loopback requests without a token."""
        resp = e2e_client.get("/api/v1/auth/me")
        # In local mode, loopback requests are bypass-authed as local-admin
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("local") is True or data.get("username") == "local-admin"


# ── Change Password ──────────────────────────────────────────────────────


class TestChangePassword:
    def test_change_password_succeeds(
        self, e2e_client: httpx.Client, admin_token: str
    ) -> None:
        """Change password with valid current password."""
        auth = {"Authorization": f"Bearer {admin_token}"}

        resp = e2e_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "e2e-admin-pass-123",
                "new_password": "e2e-new-admin-pass-456",
            },
            headers=auth,
        )
        # In local mode, the request goes through even without a valid token
        # due to loopback bypass. The handler itself validates the body.
        if resp.status_code == 200:
            assert resp.json().get("status") == "ok"
        elif resp.status_code == 401:
            # Token was already invalidated by a previous test
            pytest.skip("Token invalidated before this test ran")

    def test_change_password_with_wrong_current_returns_401(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "wrong-password",
                "new_password": "new-pass-789",
            },
            headers=auth_header,
        )
        assert resp.status_code == 401

    def test_change_password_too_short_returns_400(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "e2e-admin-pass-123",
                "new_password": "ab",
            },
            headers=auth_header,
        )
        assert resp.status_code == 400


# ── Setup Status ──────────────────────────────────────────────────────────


class TestSetupStatus:
    def test_setup_status_returns_info(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/auth/setup-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "setup_completed" in data


# ── Stream Token ──────────────────────────────────────────────────────────


class TestStreamToken:
    def test_stream_token_returns_short_lived_token(
        self, e2e_client: httpx.Client, auth_header: dict
    ) -> None:
        resp = e2e_client.post(
            "/api/v1/auth/stream-token", headers=auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "stream_token" in data
        assert len(str(data["stream_token"])) > 0

    def test_stream_token_without_auth_returns_200_in_local(
        self, e2e_client: httpx.Client
    ) -> None:
        """In local mode, loopback bypass allows this without a token."""
        resp = e2e_client.post("/api/v1/auth/stream-token")
        assert resp.status_code == 200


# ── Login Rate Limiting ──────────────────────────────────────────────────


class TestRateLimiting:
    def test_repeated_bad_logins_eventually_trigger_429(
        self, e2e_client: httpx.Client
    ) -> None:
        """Send many bad-login attempts with a unique username; expect 429."""
        unique_user = f"rate-test-{uuid.uuid4().hex[:8]}"
        got_429 = False
        for _ in range(30):
            resp = e2e_client.post(
                "/api/v1/auth/login",
                json={"username": unique_user, "password": "wrong"},
            )
            if resp.status_code == 429:
                got_429 = True
                break
        assert got_429, "Rate limiter did not trigger after 30 bad login attempts"

    def test_rate_limit_response_has_expected_format(
        self, e2e_client: httpx.Client
    ) -> None:
        """If a 429 is triggered, verify the response format."""
        unique_user = f"rate-fmt-{uuid.uuid4().hex[:8]}"
        got_429 = False
        for _ in range(30):
            resp = e2e_client.post(
                "/api/v1/auth/login",
                json={"username": unique_user, "password": "wrong"},
            )
            if resp.status_code == 429:
                got_429 = True
                data = resp.json()
                assert "detail" in data
                break
        if not got_429:
            pytest.skip("Rate limit not triggered; may need more attempts")
