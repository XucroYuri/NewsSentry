"""Phase 3: Authentication API E2E tests.

Covers login, token exchange, logout, me, change-password, setup-status, and setup.
"""

from __future__ import annotations

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
        assert data["token_type"] == "bearer"
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
    def test_logout_invalidates_token(
        self, e2e_client: httpx.Client, admin_token: str
    ) -> None:
        # Logout
        resp = e2e_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

        # After logout, the same token should be rejected (401)
        me_resp = e2e_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert me_resp.status_code in (401,)

    def test_logout_without_token_still_returns_ok(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post("/api/v1/auth/logout")
        assert resp.status_code == 200


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

    def test_me_without_token_returns_401(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token_returns_401(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalidtoken123"},
        )
        assert resp.status_code == 401


# ── Change Password ──────────────────────────────────────────────────────


class TestChangePassword:
    def test_change_password_succeeds(
        self, e2e_client: httpx.Client
    ) -> None:
        # Login as admin
        login_resp = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "e2e-admin-pass-123"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # Change password
        resp = e2e_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "e2e-admin-pass-123",
                "new_password": "e2e-new-admin-pass-456",
            },
            headers=auth,
        )
        assert resp.status_code == 200

        # Verify can login with new password
        login2 = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "e2e-new-admin-pass-456"},
        )
        assert login2.status_code == 200

        # Verify old password no longer works
        login3 = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "e2e-admin-pass-123"},
        )
        assert login3.status_code == 401

        # Reset back to original for other tests
        token2 = login2.json()["access_token"]
        e2e_client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "e2e-new-admin-pass-456",
                "new_password": "e2e-admin-pass-123",
            },
            headers={"Authorization": f"Bearer {token2}"},
        )

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
        # The admin user was bootstrapped by e2e_server fixture
        resp = e2e_client.get("/api/v1/auth/setup-status")
        assert resp.status_code == 200
        data = resp.json()
        # Since an admin exists and password was set explicitly
        assert "setup_completed" in data


# ── Stream Token ──────────────────────────────────────────────────────────


class TestStreamToken:
    def test_stream_token_requires_auth(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.post("/api/v1/auth/stream-token")
        assert resp.status_code == 401

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
