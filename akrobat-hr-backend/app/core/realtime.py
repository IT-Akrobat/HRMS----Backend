"""
Minimal WebSocket broadcast hub, used to push "something on attendance
changed" events to any connected admin dashboards the instant they
happen (see /ws/dashboard in app/main.py), instead of the frontend
polling on a timer.

Attendance actions (check-in/out, break start/end) run inside plain sync
`def` route handlers -- see app/attendance/services.py -- which FastAPI
executes in a worker thread, not on the asyncio event loop that actually
owns the WebSocket connections below. So a sync caller can't just
`await` a send; broadcast_threadsafe() hops onto the main event loop via
asyncio.run_coroutine_threadsafe(), which is safe to call from any
thread. set_main_loop() captures that loop once, from main.py's startup
event.
"""

import asyncio
import logging
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_connections: list[WebSocket] = []
_main_loop: Optional[asyncio.AbstractEventLoop] = None

# ---------------------------------------------------------------------------
# Per-employee registry, used by /ws/notifications (see app/main.py). Unlike
# the all-clients dashboard hub above, notifications are private to the
# employee they belong to, so this keys connections by employee_id instead
# of broadcasting to everyone. One employee can have several sockets open
# at once (e.g. desktop tab + phone browser both logged in), so each id maps
# to a list.
# ---------------------------------------------------------------------------
_notification_connections: dict[str, list[WebSocket]] = {}


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


async def register(websocket: WebSocket) -> None:
    _connections.append(websocket)


async def unregister(websocket: WebSocket) -> None:
    if websocket in _connections:
        _connections.remove(websocket)


async def _broadcast(event: dict[str, Any]) -> None:
    dead = []
    for ws in list(_connections):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _connections:
            _connections.remove(ws)


def broadcast_threadsafe(event: dict[str, Any]) -> None:
    """
    Fire-and-forget broadcast, safe to call from the sync request-handling
    threads the attendance routes actually run on. Never raises -- a
    check-in/out must never fail because a dashboard broadcast couldn't
    be delivered. No-ops quietly if no dashboard is connected, or if
    called before the app has finished starting up.
    """
    if _main_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(event), _main_loop)
    except Exception as e:
        logger.error(f"Failed to broadcast realtime event: {e}")


async def register_notification_socket(employee_id: str, websocket: WebSocket) -> None:
    _notification_connections.setdefault(employee_id, []).append(websocket)


async def unregister_notification_socket(
    employee_id: str, websocket: WebSocket
) -> None:
    sockets = _notification_connections.get(employee_id)
    if not sockets:
        return
    if websocket in sockets:
        sockets.remove(websocket)
    if not sockets:
        _notification_connections.pop(employee_id, None)


async def _send_to_employee(employee_id: str, event: dict[str, Any]) -> None:
    sockets = list(_notification_connections.get(employee_id, []))
    dead = []
    for ws in sockets:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        await unregister_notification_socket(employee_id, ws)


def broadcast_to_employee_threadsafe(employee_id: str, event: dict[str, Any]) -> None:
    """
    Same fire-and-forget/thread-safe contract as broadcast_threadsafe()
    above, but targeted at just the given employee's open socket(s)
    instead of every connected dashboard. Used by
    app/notifications/services.py::notify_employee() so a new
    notification reaches an already-open tab the instant it's written,
    instead of waiting for the frontend's next poll. No-ops quietly if
    that employee has no socket open right now (they'll just see it on
    next login/GET /notifications/my) or before the app has finished
    starting up.
    """
    if _main_loop is None or not employee_id:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            _send_to_employee(str(employee_id), event), _main_loop
        )
    except Exception as e:
        logger.error(f"Failed to send realtime notification to {employee_id}: {e}")
