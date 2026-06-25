"""E2E test fixtures — manage a uvicorn subprocess and httpx client."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``e2e`` marker so ``pytest --strict-markers`` does not reject it."""
    config.addinivalue_line(
        "markers",
        "e2e: End-to-end test that requires a running API server (via uvicorn subprocess).",
    )


@pytest.fixture(scope="session")
def e2e_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fresh temporary data directory for the E2E server.

    Override by setting ``NEWSSENTRY_E2E_DATA_DIR`` env var (e.g. in CI to reuse).
    """
    env_dir = os.environ.get("NEWSSENTRY_E2E_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return tmp_path_factory.mktemp("e2e-data")


@pytest.fixture(scope="session")
def e2e_port() -> int:
    """Port the E2E server listens on.

    Override by setting ``NEWSSENTRY_E2E_PORT`` env var (default 18082).
    """
    return int(os.environ.get("NEWSSENTRY_E2E_PORT", "18082"))


@pytest.fixture(scope="session")
def e2e_server(
    e2e_data_dir: Path,
    e2e_port: int,
) -> Iterator[int]:
    """Start a uvicorn subprocess with a clean in-memory store and data directory.

    The server is started **once** per test session.  Cleanup kills the process.
    """
    env = os.environ.copy()
    env.update({
        "NEWSSENTRY_DATA_DIR": str(e2e_data_dir),
        "NEWSSENTRY_AUTO_COLLECT": "0",
        "NEWSSENTRY_AI_ENRICHMENT": "0",
        "NEWSSENTRY_PUBLIC_TRANSLATION": "0",
        "NEWSSENTRY_DEPLOYMENT_ENV": "local",
        "NEWSSENTRY_API_KEY": "e2e-test-api-key-00000000",
        "CORS_ALLOWED_ORIGINS": "http://localhost:18082",
    })

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "news_sentry.core.api_server:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(e2e_port),
        "--log-level",
        "warning",
    ]

    proc = subprocess.Popen(  # noqa: S603
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for the server to become healthy (up to 15 seconds)
    health_url = f"http://127.0.0.1:{e2e_port}/api/v1/health"
    deadline = time.monotonic() + 15
    started = False
    while time.monotonic() < deadline:
        try:
            r = httpx.get(health_url, timeout=2.0)
            if r.status_code == 200:
                started = True
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.5)

    if not started:
        proc.kill()
        proc.wait(timeout=5)
        pytest.exit(
            f"E2E server failed to start on port {e2e_port}.\nstderr: {stderr_tail}",
            returncode=1,
        )

    yield e2e_port

    # Teardown
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture(scope="session")
def e2e_base_url(e2e_port: int) -> str:
    """Base URL string, e.g. ``http://127.0.0.1:18082``."""
    return f"http://127.0.0.1:{e2e_port}"


@pytest.fixture(scope="session")
def e2e_client(e2e_server: int, e2e_base_url: str) -> Iterator[httpx.Client]:
    """A synchronous ``httpx.Client`` pointed at the E2E server.

    The client uses keep-alive so that multiple test functions share
    a TCP connection where possible.
    """
    with httpx.Client(base_url=e2e_base_url, timeout=10.0) as client:
        yield client


# ── Auth helpers ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def admin_token(e2e_client: httpx.Client) -> str:
    """Create admin user via /api/v1/auth/setup and return a Bearer token.

    When the E2E server starts from a fresh data directory there are no users,
    so ``auth/setup`` will succeed and return a token directly.
    If setup returns 409 (already exists), fall back to login.
    """
    resp = e2e_client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "e2e-admin-pass-123"},
    )
    if resp.status_code == 200:
        data = resp.json()
        return str(data["access_token"])
    if resp.status_code == 409:
        # Setup already completed (e.g. data dir reused); log in
        login_resp = e2e_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "e2e-admin-pass-123"},
        )
        assert login_resp.status_code == 200, (
            f"Admin login fallback failed: {login_resp.text}"
        )
        return str(login_resp.json()["access_token"])
    raise AssertionError(f"Admin setup failed: {resp.status_code} {resp.text}")


@pytest.fixture(scope="session")
def auth_header(admin_token: str) -> dict[str, str]:
    """``Authorization: Bearer <token>`` header dict."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def reader_token(e2e_client: httpx.Client, admin_token: str) -> str:
    """Create a reader-role user and return their token.

    This fixture depends on an already-active admin session (``admin_token``).
    """
    auth = {"Authorization": f"Bearer {admin_token}"}
    # Create a reader user
    resp = e2e_client.post(
        "/api/v1/admin/users",
        json={"username": "e2e-reader", "password": "e2e-reader-pass", "role": "reader"},
        headers=auth,
    )
    assert resp.status_code == 200, f"Create reader user failed: {resp.text}"

    # Log in as the reader
    resp = e2e_client.post(
        "/api/v1/auth/login",
        json={"username": "e2e-reader", "password": "e2e-reader-pass"},
    )
    assert resp.status_code == 200, f"Reader login failed: {resp.text}"
    return str(resp.json()["access_token"])


@pytest.fixture(scope="session")
def reader_header(reader_token: str) -> dict[str, str]:
    """Authorization header for the reader user."""
    return {"Authorization": f"Bearer {reader_token}"}
