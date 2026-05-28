"""WebSocket connection manager for per-scan live log streaming.

Architecture
------------
Each scan gets its own :class:`asyncio.Queue` of :class:`ScanEvent` dicts.
The WebSocket endpoint dequeues events and forwards them to the connected
client.  The :class:`~app.application.scan_event_bus.ScanEventBus` puts events
onto the queue from the orchestrator.

Lifetime
--------
- A queue is created on first connection or first event publish (whichever
  comes first).
- The queue and all connection state are cleaned up when
  :meth:`ConnectionManager.cleanup_scan` is called (by the Arq worker after
  the scan finishes).

Concurrency limits
------------------
A maximum of ``MAX_CONNECTIONS_PER_SCAN`` WebSocket connections may be active
for a single scan at once.  Additional connection attempts receive 1008
(Policy Violation).

Thread safety
-------------
All state is protected by a single :class:`asyncio.Lock`.  All methods are
``async`` and must be awaited from the event loop.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_CONNECTIONS_PER_SCAN = 5
_EVENT_QUEUE_MAX_SIZE = 1000  # drop oldest events if queue fills up


class ConnectionManager:
    """Manages WebSocket connections and event queues for active scans.

    This is a singleton — import and use :data:`manager` from this module.
    """

    def __init__(self) -> None:
        # scan_id (str) → list[WebSocket]
        self._connections: dict[str, list[WebSocket]] = {}
        # scan_id (str) → asyncio.Queue
        self._queues: dict[str, asyncio.Queue] = {}  # type: ignore[type-arg]
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, scan_id: str, websocket: WebSocket) -> bool:
        """Accept a WebSocket connection for *scan_id*.

        Returns ``True`` if accepted, ``False`` if the connection limit is
        reached (the caller should close with code 1008).
        """
        async with self._lock:
            existing = self._connections.get(scan_id, [])
            if len(existing) >= MAX_CONNECTIONS_PER_SCAN:
                logger.warning(
                    "ws_manager.connection_limit_reached",
                    scan_id=scan_id,
                    limit=MAX_CONNECTIONS_PER_SCAN,
                )
                return False

            await websocket.accept()
            self._connections.setdefault(scan_id, []).append(websocket)
            # Ensure queue exists.
            self._queues.setdefault(scan_id, asyncio.Queue(maxsize=_EVENT_QUEUE_MAX_SIZE))
            logger.info(
                "ws_manager.connected",
                scan_id=scan_id,
                total=len(self._connections[scan_id]),
            )
            return True

    async def disconnect(self, scan_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from the active connection set."""
        async with self._lock:
            conns = self._connections.get(scan_id, [])
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                self._connections.pop(scan_id, None)
            logger.info("ws_manager.disconnected", scan_id=scan_id)

    async def cleanup_scan(self, scan_id: str) -> None:
        """Remove all connection and queue state for a finished scan.

        Called by the Arq worker (or orchestrator) after the scan reaches a
        terminal state.  Sends a sentinel ``None`` to unblock any waiting
        consumers before clearing the queue.
        """
        async with self._lock:
            queue = self._queues.pop(scan_id, None)
            if queue is not None:
                try:
                    queue.put_nowait(None)  # sentinel to unblock consumers
                except asyncio.QueueFull:
                    pass
            self._connections.pop(scan_id, None)
            logger.debug("ws_manager.cleanup", scan_id=scan_id)

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def publish(self, scan_id: str, event: dict[str, Any]) -> None:
        """Put *event* on the scan's queue.

        If the queue is full the oldest item is discarded (non-blocking drop).
        Creates the queue on first use so the orchestrator can start
        publishing before any client connects.
        """
        async with self._lock:
            queue = self._queues.setdefault(
                scan_id, asyncio.Queue(maxsize=_EVENT_QUEUE_MAX_SIZE)
            )

        if queue.full():
            try:
                queue.get_nowait()  # discard oldest
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # still full after drain — silently drop

    # ------------------------------------------------------------------
    # Queue consumer (used by WebSocket endpoint)
    # ------------------------------------------------------------------

    async def consume(self, scan_id: str) -> "asyncio.Queue[dict | None]":
        """Return the event queue for *scan_id*, creating it if necessary."""
        async with self._lock:
            return self._queues.setdefault(
                scan_id, asyncio.Queue(maxsize=_EVENT_QUEUE_MAX_SIZE)
            )

    # ------------------------------------------------------------------
    # Broadcast to connected WebSockets (best-effort)
    # ------------------------------------------------------------------

    async def broadcast(self, scan_id: str, event: dict[str, Any]) -> None:
        """Send *event* directly to all connected WebSocket clients for *scan_id*.

        Errors on individual sockets are caught and the socket removed.
        This is a secondary delivery path; the primary path is the queue consumer
        loop in the WebSocket endpoint.
        """
        async with self._lock:
            conns = list(self._connections.get(scan_id, []))

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:  # noqa: BLE001
                dead.append(ws)

        for ws in dead:
            await self.disconnect(scan_id, ws)


# Module-level singleton — imported by the WebSocket endpoint and event bus.
manager = ConnectionManager()
