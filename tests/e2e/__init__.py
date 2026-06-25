"""E2E tests — real HTTP requests to a running NewsSentry API server.

Uses ``uvicorn`` subprocess fixture and ``httpx`` client.
Mark with ``@pytest.mark.e2e``; excluded from default ``pytest`` run.
"""
