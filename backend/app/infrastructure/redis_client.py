"""Redis helpers for the scan task queue system.

Provides:
- :class:`RedisClient` — thin wrapper around an ArqRedis pool with three
  distinct concerns: distributed repo locks, scan cancellation flags, and
  pool lifecycle management.

Lock semantics
--------------
``scan:lock:repo:{repository_id}``

  Acquired **before** a scan record is created (in the API handler).
  Value = str(scan_id) so any process can verify ownership before releasing.
  TTL = ``settings.scan_lock_ttl_seconds`` (> job timeout) so the key
  self-expires if a worker crashes before explicit release.

  Acquire with SET NX (atomic, no WATCH/EXEC needed).
  Release only if the stored value matches the expected scan_id (prevents
  accidental release of another scan's lock after a crash+restart scenario).

Cancellation flag
-----------------
``scan:cancel:{scan_id}``

  Set by the API cancel endpoint.  The orchestrator polls this key between
  pipeline stages and raises :class:`~app.core.exceptions.ScanCancelledError`
  when it is present.  Cleared by the worker after the scan finishes/is
  cancelled.  TTL = 1 h as a safety net.
"""
from __future__ import annotations

import uuid

from app.core.logging import get_logger

logger = get_logger(__name__)

_LOCK_KEY_PREFIX = "scan:lock:repo:"
_CANCEL_KEY_PREFIX = "scan:cancel:"
_CANCEL_KEY_TTL = 3600  # 1 hour — safety-net expiry


class RedisClient:
    """High-level async Redis helper for scan lifecycle operations.

    Accepts any object that implements the async redis interface
    (``arq.connections.ArqRedis`` or ``redis.asyncio.Redis``).
    """

    def __init__(self, pool: object) -> None:
        self._pool = pool  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Repository distributed lock
    # ------------------------------------------------------------------

    async def acquire_repo_lock(
        self,
        repository_id: uuid.UUID,
        scan_id: uuid.UUID,
        ttl_seconds: int,
    ) -> bool:
        """Try to acquire an exclusive lock for *repository_id*.

        Uses ``SET NX PX`` — atomic, no Lua script required.

        Returns:
            ``True`` if the lock was acquired; ``False`` if another scan
            already holds it.
        """
        key = f"{_LOCK_KEY_PREFIX}{repository_id}"
        result = await self._pool.set(  # type: ignore[union-attr]
            key,
            str(scan_id),
            nx=True,
            px=ttl_seconds * 1000,
        )
        acquired = result is not None
        logger.debug(
            "redis.repo_lock",
            repository_id=str(repository_id),
            scan_id=str(scan_id),
            acquired=acquired,
        )
        return acquired

    async def release_repo_lock(
        self,
        repository_id: uuid.UUID,
        scan_id: uuid.UUID,
    ) -> None:
        """Release the lock for *repository_id* **only if** we own it.

        Ownership is verified by comparing the stored value against *scan_id*.
        A mismatch (e.g. lock expired and was acquired by a different scan)
        is logged and silently ignored — never raises.
        """
        key = f"{_LOCK_KEY_PREFIX}{repository_id}"
        raw = await self._pool.get(key)  # type: ignore[union-attr]

        if raw is None:
            logger.debug(
                "redis.repo_lock_release.already_expired",
                repository_id=str(repository_id),
            )
            return

        stored = raw.decode() if isinstance(raw, bytes) else str(raw)
        if stored != str(scan_id):
            logger.warning(
                "redis.repo_lock_release.ownership_mismatch",
                repository_id=str(repository_id),
                expected=str(scan_id),
                found=stored,
            )
            return

        await self._pool.delete(key)  # type: ignore[union-attr]
        logger.debug(
            "redis.repo_lock_released",
            repository_id=str(repository_id),
            scan_id=str(scan_id),
        )

    # ------------------------------------------------------------------
    # Scan cancellation flag
    # ------------------------------------------------------------------

    async def request_cancellation(self, scan_id: uuid.UUID) -> None:
        """Set the cancellation flag for *scan_id*."""
        key = f"{_CANCEL_KEY_PREFIX}{scan_id}"
        await self._pool.set(key, "1", ex=_CANCEL_KEY_TTL)  # type: ignore[union-attr]
        logger.info("redis.cancel_requested", scan_id=str(scan_id))

    async def is_cancel_requested(self, scan_id: uuid.UUID) -> bool:
        """Return ``True`` if a cancellation has been requested for *scan_id*."""
        key = f"{_CANCEL_KEY_PREFIX}{scan_id}"
        count = await self._pool.exists(key)  # type: ignore[union-attr]
        return bool(count)

    async def clear_cancel_flag(self, scan_id: uuid.UUID) -> None:
        """Remove the cancellation flag (called after scan finishes)."""
        key = f"{_CANCEL_KEY_PREFIX}{scan_id}"
        await self._pool.delete(key)  # type: ignore[union-attr]
        logger.debug("redis.cancel_flag_cleared", scan_id=str(scan_id))


async def create_redis_pool():  # type: ignore[return]
    """Create and return an ArqRedis connection pool using the app settings.

    Import is deferred to avoid importing arq at module load time in test
    environments where arq may not be available or configured.
    """
    from arq.connections import RedisSettings, create_pool  # type: ignore[import-untyped]

    from app.core.config import settings

    return await create_pool(RedisSettings.from_dsn(settings.redis_url))
