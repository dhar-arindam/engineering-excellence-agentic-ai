"""Scan event bus — typed events from the orchestrator to WebSocket clients.

The event bus is a thin façade over :class:`~app.infrastructure.websocket_manager.ConnectionManager`.
The orchestrator calls the high-level methods (``log``, ``progress``, ``status``)
and the bus serialises them into the canonical event envelope:

.. code-block:: json

    {
        "type": "log" | "progress" | "status",
        "message": "string",
        "progress": 42,           // present on "progress" events
        "status": "running"       // present on "status" events
    }

Design notes
------------
- All methods are fire-and-forget ``async`` coroutines — they never raise.
- When no WebSocket client is connected the events are still published to the
  queue so a late-connecting client can replay recent history (up to queue
  capacity).
- Injecting the event bus into the orchestrator keeps infrastructure concerns
  out of the application layer; tests can replace it with a no-op stub.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.core.logging import get_logger
from app.infrastructure.websocket_manager import ConnectionManager, manager as _default_manager

logger = get_logger(__name__)


class ScanEventBus:
    """Publishes typed scan events to the WebSocket connection manager.

    Args:
        scan_id:    The UUID of the scan this bus is scoped to.
        connection_manager: Injected manager (defaults to the module singleton).
    """

    def __init__(
        self,
        scan_id: uuid.UUID,
        connection_manager: ConnectionManager | None = None,
    ) -> None:
        self._scan_id = str(scan_id)
        self._manager = connection_manager or _default_manager

    # ------------------------------------------------------------------
    # Public event emitters
    # ------------------------------------------------------------------

    async def log(self, message: str) -> None:
        """Emit a human-readable log line."""
        await self._publish({"type": "log", "message": message})

    async def progress(self, percentage: int, message: str = "") -> None:
        """Emit a progress update (0–100)."""
        await self._publish(
            {
                "type": "progress",
                "message": message or f"Progress: {percentage}%",
                "progress": max(0, min(100, percentage)),
            }
        )

    async def status(self, status: str, message: str = "") -> None:
        """Emit a status change notification."""
        await self._publish(
            {
                "type": "status",
                "message": message or f"Status changed to '{status}'",
                "status": status,
            }
        )

    async def cleanup(self) -> None:
        """Signal that the scan has finished; cleans up queue and connections."""
        await self._manager.cleanup_scan(self._scan_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish(self, event: dict[str, Any]) -> None:
        try:
            await self._manager.publish(self._scan_id, event)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "scan_event_bus.publish_error",
                scan_id=self._scan_id,
                error=str(exc),
            )
