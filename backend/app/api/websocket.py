"""WebSocket endpoint for live scan log streaming.

Endpoint
--------
``GET /ws/scans/{scan_id}``

Client connects, then receives a stream of JSON events:

.. code-block:: json

    {"type": "log",      "message": "Agent starting: SecurityExpertAgent"}
    {"type": "progress", "message": "Progress: 45%", "progress": 45}
    {"type": "status",   "message": "Status changed to 'completed'", "status": "completed"}

Connection closes automatically when the scan reaches a terminal state
(the orchestrator calls ``ScanEventBus.cleanup()`` → ``ConnectionManager.cleanup_scan()``
which sends a ``None`` sentinel on the queue).

Security
--------
- Max ``MAX_CONNECTIONS_PER_SCAN`` (5) concurrent WebSocket connections per scan.
  Excess connections are rejected with code 1008.
- Unknown ``scan_id`` values receive a 1008 close immediately (no DB lookup
  to prevent timing-based scan enumeration).
- All reads from the queue include an outer ``asyncio.wait_for`` so a stale
  connection cannot hold server resources indefinitely.

Design
------
- The endpoint never blocks the event loop — queue.get() is awaited.
- ``WebSocketDisconnect`` is caught and handled gracefully.
- The send loop exits on sentinel ``None`` (scan finished) or client disconnect.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.infrastructure.websocket_manager import manager

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket"])

# How long to wait for the next event before sending a keepalive ping.
_QUEUE_WAIT_TIMEOUT: float = 30.0
# Total maximum lifetime of a WebSocket connection (seconds).
_WS_MAX_LIFETIME: float = 3600.0


@router.websocket("/ws/scans/{scan_id}")
async def scan_log_stream(websocket: WebSocket, scan_id: uuid.UUID) -> None:
    """Stream live log, progress, and status events for *scan_id*.

    Events are pushed by :class:`~app.application.scan_event_bus.ScanEventBus`
    (running inside the Arq worker) and forwarded here via an
    :class:`asyncio.Queue`.

    Example event payloads:

    .. code-block:: json

        {"type": "log",      "message": "Ingesting repository (max_files=200)…"}
        {"type": "progress", "message": "Progress: 25%", "progress": 25}
        {"type": "status",   "message": "Status changed to 'running'", "status": "running"}
        {"type": "status",   "message": "Scan completed. Overall score: 87", "status": "completed"}
    """
    scan_id_str = str(scan_id)

    accepted = await manager.connect(scan_id_str, websocket)
    if not accepted:
        # Connection limit reached — reject with Policy Violation.
        await websocket.close(code=1008, reason="Connection limit reached for this scan.")
        return

    logger.info("ws.scan_log_stream.connected", scan_id=scan_id_str)

    try:
        queue = await manager.consume(scan_id_str)
        deadline = asyncio.get_event_loop().time() + _WS_MAX_LIFETIME

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.info("ws.scan_log_stream.max_lifetime_reached", scan_id=scan_id_str)
                break

            wait = min(_QUEUE_WAIT_TIMEOUT, remaining)
            try:
                event = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                # Send a keepalive ping so proxies/browsers don't close idle connections.
                try:
                    await websocket.send_text(
                        json.dumps({"type": "ping", "message": "keepalive"})
                    )
                except Exception:  # noqa: BLE001
                    break
                continue

            # Sentinel None means the scan finished and the queue was cleaned up.
            if event is None:
                logger.info("ws.scan_log_stream.scan_finished", scan_id=scan_id_str)
                break

            try:
                await websocket.send_text(json.dumps(event))
            except WebSocketDisconnect:
                break
            except Exception:  # noqa: BLE001
                break

    except WebSocketDisconnect:
        logger.info("ws.scan_log_stream.client_disconnected", scan_id=scan_id_str)
    except Exception as exc:  # noqa: BLE001
        logger.error("ws.scan_log_stream.error", scan_id=scan_id_str, error=str(exc))
    finally:
        await manager.disconnect(scan_id_str, websocket)
        logger.info("ws.scan_log_stream.closed", scan_id=scan_id_str)


# Frontend uses /api/scans/{scan_id}/logs — register same handler under that path.
router.add_websocket_route("/api/scans/{scan_id}/logs", scan_log_stream)
