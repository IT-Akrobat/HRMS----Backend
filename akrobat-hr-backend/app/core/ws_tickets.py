"""
Short-lived, single-use tickets for authenticating WebSocket connections.

Why this exists: the WS handshake used to rely purely on the httpOnly
access-token cookie (see app/main.py). That only works when the browser
actually has the cookie for this domain, which is not the case on iOS/
Safari when the frontend is proxied through a different site (Vercel's
free rewrite proxy makes normal fetch() calls same-origin, but Vercel
can't proxy a persistent WebSocket upgrade to an external host -- so the
WS connection still goes straight to this API's own domain, where an
iPhone was never allowed to store the cookie in the first place).

Instead: the frontend calls GET /auth/ws-ticket (a normal fetch, which
*does* go through the proxy and *does* carry the cookie) to mint a
ticket, then opens the socket as wss://.../ws/dashboard?ticket=...
Tickets are single-use and expire in 30s, so even if one leaked (e.g. in
a proxy access log) it's worthless almost immediately.

In-memory only -- fine for a single backend instance. If this ever runs
behind more than one worker/instance, swap this dict for Redis (same
get/pop-with-expiry shape) or the ticket minted on instance A won't be
found when the WS lands on instance B.
"""

import secrets
import time

_TICKET_TTL_SECONDS = 30
_tickets: dict[str, tuple[str, float]] = {}  # ticket -> (user_id, expires_at)


def issue_ticket(user_id: str) -> str:
    _purge_expired()
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (user_id, time.monotonic() + _TICKET_TTL_SECONDS)
    return ticket


def redeem_ticket(ticket: str) -> str | None:
    """Single-use: returns the user_id and removes the ticket, or None if
    the ticket is missing/expired/already used."""
    entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    user_id, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    return user_id


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [t for t, (_, exp) in _tickets.items() if exp < now]
    for t in expired:
        _tickets.pop(t, None)
