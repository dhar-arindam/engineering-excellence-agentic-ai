"""Arq worker definition for the scan task queue.

Running the worker
------------------
From the repo root (inside the Docker container or virtualenv)::

    python -m arq app.infrastructure.arq_worker.WorkerSettings

Or via the docker-compose ``worker`` service.

Architecture
------------
- ``scan_task`` is the single Arq task function that drives scan execution.
- ``WorkerSettings`` configures concurrency, timeout, and queue name from
  ``app.core.config.settings``.
- ``on_startup`` / ``on_shutdown`` hooks initialise/tear down the SQLAlchemy
  engine so each worker process has its own connection pool.

Concurrency & timeout
---------------------
- ``max_jobs = settings.scan_max_concurrent`` (default 3) — hard cap on parallel
  scans per worker process.  Scale horizontally by adding more worker replicas.
- ``job_timeout = settings.scan_timeout_seconds`` (default 600 s) — Arq cancels
  the asyncio task if it runs longer, which surfaces as ``asyncio.CancelledError``
  inside ``scan_task`` (treated as a failure, status → "failed").

Per-repository lock
-------------------
The lock is acquired by the API handler before enqueuing.  ``scan_task`` is
responsible for releasing it after the scan finishes (success, failure, or
cancellation) via :meth:`RedisClient.release_repo_lock`.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ScanStatus
from app.infrastructure.redis_client import RedisClient

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Task function
# ---------------------------------------------------------------------------

async def scan_task(
    ctx: dict,  # Arq worker context — ctx['redis'] is an ArqRedis pool
    scan_id_str: str,
    repository_id_str: str,
) -> dict:  # type: ignore[type-arg]
    """Arq task: run a full scan pipeline for *scan_id*.

    Args:
        ctx:               Arq worker context; ``ctx['redis']`` is the pool.
        scan_id_str:       String form of the scan UUID.
        repository_id_str: String form of the owning repository UUID (for lock release).

    Returns:
        Dict with ``scan_id`` and final ``status`` — stored by Arq as job result.

    Note: branch and scan_config are read directly from the DB by the orchestrator
    (they are persisted before the job is enqueued), so they are not passed as
    task arguments.
    """
    scan_id = uuid.UUID(scan_id_str)
    repository_id = uuid.UUID(repository_id_str)
    redis_client = RedisClient(ctx["redis"])

    logger.info("arq.scan_task.start", scan_id=scan_id_str)

    # If cancel was requested while the job was still queued, skip the pipeline.
    if await redis_client.is_cancel_requested(scan_id):
        logger.info("arq.scan_task.cancelled_before_start", scan_id=scan_id_str)
        async with _open_repo() as scan_repo:
            await scan_repo.update_scan_status(scan_id, ScanStatus.CANCELLED)
        await redis_client.release_repo_lock(repository_id, scan_id)
        await redis_client.clear_cancel_flag(scan_id)
        return {"scan_id": scan_id_str, "status": ScanStatus.CANCELLED.value}

    try:
        await _execute_scan(scan_id, redis_client)
    finally:
        # Always release the lock and clean up cancel flag.
        await redis_client.release_repo_lock(repository_id, scan_id)
        await redis_client.clear_cancel_flag(scan_id)

    logger.info("arq.scan_task.done", scan_id=scan_id_str)
    return {"scan_id": scan_id_str, "status": "done"}


async def _execute_scan(scan_id: uuid.UUID, redis_client: RedisClient) -> None:
    """Wire all dependencies and run the ScanOrchestrator pipeline."""
    from app.api.deps import (
        get_agents,
        get_github_loader,
        get_local_loader,
        get_scoring_engine,
        get_tool_services,
    )
    from app.application.scan_event_bus import ScanEventBus
    from app.application.scan_orchestrator import ScanOrchestrator
    from app.application.source_preparation import SourcePreparationService
    from app.infrastructure.db.scan_repository import open_scan_repository
    from app.infrastructure.github_clone import GitHubCloner
    from app.infrastructure.local_repo_validator import LocalRepoValidator

    tools = get_tool_services()
    github_cloner = GitHubCloner()
    event_bus = ScanEventBus(scan_id)

    async with open_scan_repository() as scan_repo:
        orchestrator = ScanOrchestrator(
            scan_repository=scan_repo,
            source_preparation=SourcePreparationService(
                github_cloner=github_cloner,
                local_validator=LocalRepoValidator(),
            ),
            agents=get_agents(),
            scoring_engine=get_scoring_engine(),
            local_loader=get_local_loader(),
            github_loader=get_github_loader(),
            code_service=tools["code"],
            test_service=tools["test"],
            cicd_service=tools["cicd"],
            security_service=tools["security"],
            architecture_service=tools["architecture"],
            github_cloner=github_cloner,
            redis_client=redis_client,
            pipeline_timeout=float(settings.scan_timeout_seconds),
            event_bus=event_bus,
        )
        await orchestrator.run_scan(scan_id)


def _open_repo():  # type: ignore[return]
    """Convenience wrapper to avoid repeating the import in scan_task."""
    from app.infrastructure.db.scan_repository import open_scan_repository
    return open_scan_repository()


# ---------------------------------------------------------------------------
# Worker lifecycle hooks
# ---------------------------------------------------------------------------

async def on_startup(ctx: dict) -> None:  # type: ignore[type-arg]
    """Called once when the worker process starts."""
    logger.info("arq.worker.startup")
    # Nothing extra needed — DB sessions are created per-job via open_scan_repository().


async def on_shutdown(ctx: dict) -> None:  # type: ignore[type-arg]
    """Called once when the worker process stops."""
    logger.info("arq.worker.shutdown")


# ---------------------------------------------------------------------------
# WorkerSettings — consumed by `python -m arq app.infrastructure.arq_worker.WorkerSettings`
# ---------------------------------------------------------------------------

# Compute redis_settings at module load time so Arq can access it as a class attribute.
def _get_redis_settings():  # type: ignore[return]
    """Create RedisSettings from the configured URL."""
    from arq.connections import RedisSettings  # type: ignore[import-untyped]
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    """Arq WorkerSettings class — configure via environment variables."""

    functions = [scan_task]
    on_startup = on_startup
    on_shutdown = on_shutdown

    # Compute redis_settings at module load time.
    # This class will be imported by Arq, which accesses these attributes directly.
    redis_settings = _get_redis_settings()

    max_jobs = settings.scan_max_concurrent
    job_timeout = settings.scan_timeout_seconds
    queue_name = settings.scan_queue_name
    keep_result = 3600  # Keep job results in Redis for 1 hour for debugging.
    retry_jobs = False  # Scans are not idempotent — do not auto-retry on failure.
