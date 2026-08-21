"""
Short-lived tickets for authenticating WebSocket connections.

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

Implementation: a short-lived signed JWT, NOT a server-side lookup.

This used to be an in-memory dict (ticket -> user_id), which only works
for a single backend process. This API actually runs behind gunicorn
with multiple UvicornWorker processes (see Procfile), each with its own
private memory -- GET /auth/ws-ticket and the WS upgrade are two
separate requests that Render's load balancer can (and mostly does)
route to two different workers, so the worker handling the WS upgrade
would never see the ticket the other worker minted. That was silently
failing the large majority of connections (~3/4 of them with 4 workers)
with a 4401 close, which is indistinguishable in the browser from a
generic "connection failed".

A signed token sidesteps the shared-state problem entirely: any worker
can verify it on its own using SUPABASE_JWT_SECRET, no lookup required.
Scoped with its own `aud` ("ws-ticket") so it can never be confused with
or substituted for a real Supabase access token by get_current_user()
(which requires aud="authenticated") -- it only ever unlocks the WS
handshake, nothing else, and only for _TICKET_TTL_SECONDS.

Trade-off: this is no longer single-use (there's nothing to mark
"already redeemed" without reintroducing shared state). Given the token
(a) expires in 30s and (b) only ever grants a *read-only* subscription
to already-permission-checked broadcast events -- never an API call, a
mutation, or a way to mint another ticket -- a replay within that window
is a low-value target. If that trade-off ever stops being acceptable
(e.g. tickets start leaking into logs somewhere), swap in a Redis-backed
single-use store instead; the issue_ticket()/redeem_ticket() signatures
below are deliberately unchanged so callers wouldn't need to change.
"""

import time
import uuid

import jwt

from app.core.config import SUPABASE_JWT_SECRET

_TICKET_TTL_SECONDS = 30
_TICKET_AUDIENCE = "ws-ticket"


def issue_ticket(user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "aud": _TICKET_AUDIENCE,
        "iat": now,
        "exp": now + _TICKET_TTL_SECONDS,
        # Not currently checked anywhere (see module docstring on the
        # single-use trade-off) -- included so a future single-use store
        # has a ready-made replay key without changing the token shape.
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def redeem_ticket(ticket: str) -> str | None:
    """Returns the user_id if `ticket` is a validly-signed, unexpired
    ws-ticket, or None if it's missing/malformed/expired/forged."""
    if not ticket:
        return None

    try:
        payload = jwt.decode(
            ticket,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=_TICKET_AUDIENCE,
        )
    except jwt.PyJWTError:
        return None

    return payload.get("sub")
