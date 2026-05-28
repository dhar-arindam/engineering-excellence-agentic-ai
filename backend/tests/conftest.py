"""Root-level pytest configuration.

Provides autouse fixtures that apply to **all** tests so individual test
modules don't need to repeat boilerplate patching.

Redis pool isolation
--------------------
Unit tests have no real Redis available.  The ``mock_arq_pool`` fixture
(autouse, session-scoped) patches :func:`app.infrastructure.redis_client.create_redis_pool`
with a coroutine that returns an ``AsyncMock`` pool.  The mock pool exposes all
Redis commands used by the codebase (``set``, ``get``, ``exists``, ``delete``,
``enqueue_job``, ``aclose``) as no-op async stubs.

Any test that *does* need a live Redis connection (integration tests) should
import and use a separate fixture that skips when Redis is unavailable.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_fake_pool() -> MagicMock:
    """Return an AsyncMock that satisfies all Redis/Arq interactions in tests."""
    pool = MagicMock()
    # Arq enqueue
    fake_job = MagicMock()
    fake_job.job_id = "test-job-id"
    pool.enqueue_job = AsyncMock(return_value=fake_job)
    # Redis commands used by RedisClient
    pool.set = AsyncMock(return_value=True)
    pool.get = AsyncMock(return_value=None)
    pool.exists = AsyncMock(return_value=0)
    pool.delete = AsyncMock(return_value=1)
    # Pool lifecycle
    pool.aclose = AsyncMock(return_value=None)
    return pool


@pytest.fixture(autouse=True, scope="session")
def mock_arq_pool():
    """Patch ``create_redis_pool`` for the entire test session.

    This prevents any attempt to connect to Redis during FastAPI lifespan
    startup when tests instantiate the app via ``create_app()`` / TestClient.
    """
    fake_pool = _make_fake_pool()

    async def _fake_create_redis_pool():
        return fake_pool

    with patch(
        "app.infrastructure.redis_client.create_redis_pool",
        new=_fake_create_redis_pool,
    ):
        yield fake_pool
