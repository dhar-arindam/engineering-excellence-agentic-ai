"""Background task execution helpers for scan-based workflows.

This module replaces the previous ``asyncio.create_task`` approach with an
Arq task queue backed by Redis.

Benefits of the Arq approach
-----------------------------
- Scans survive API server restarts (jobs are durable in Redis).
- Hard concurrency cap via ``WorkerSettings.max_jobs``.
- Per-job timeout enforced by the Arq worker (kills stuck jobs cleanly).
- Horizontal scaling: add more worker replicas without changing the API.
- Job results and errors are queryable via the Arq result backend.

Enqueuing
---------
:func:`enqueue_scan` is the only public symbol.  The API handler calls it
after creating the scan record and acquiring the per-repository lock.
The actual task function lives in :mod:`app.infrastructure.arq_worker`.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def enqueue_scan(pool: object, scan_id: uuid.UUID, repository_id: uuid.UUID) -> str:
    """Enqueue a scan job on the Arq task queue.

    Args:
        pool:          An ``ArqRedis`` pool (stored on ``app.state.arq_pool``).
        scan_id:       UUID of the already-created scan record.
        repository_id: UUID of the owning repository (passed to the task for
                       lock release).

    Returns:
        The Arq job ID string (useful for debugging).

    Raises:
        Exception: Propagates any Redis connection errors so the API handler
                   can return 503 rather than silently losing the job.
    """
    job = await pool.enqueue_job(  # type: ignore[union-attr]
        "scan_task",
        str(scan_id),
        str(repository_id),
        _queue_name=settings.scan_queue_name,
    )
    job_id: str = job.job_id if job else "unknown"
    logger.info(
        "scan.enqueued",
        scan_id=str(scan_id),
        repository_id=str(repository_id),
        job_id=job_id,
        queue=settings.scan_queue_name,
    )
    return job_id

