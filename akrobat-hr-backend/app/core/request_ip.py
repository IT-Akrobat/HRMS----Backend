"""
Shared helper for resolving the real client IP behind a proxy.

Why this exists: when the frontend is proxied through something like a
free Vercel rewrite (see vercel.json / apiClient.js -- done so the
httpOnly auth cookie survives iOS/Safari's third-party-cookie block),
every request Render sees arrives from Vercel's own server, not the
end user's browser. `request.client.host` (the raw TCP connection) is
Vercel's IP for *every* user in that setup -- useless for rate limiting
and misleading in audit/attendance logs.

Vercel (like any standard reverse proxy) forwards the real originating
IP in the `X-Forwarded-For` header, so every call site that needs "the
user's IP" should go through this helper instead of reading
`request.client.host` directly. Used by:
  - app/core/limiter.py (login rate limiting)
  - app/auth/services.py (login IP logging -- already did this before
    the other call sites did; kept here as the single source of truth)
  - app/attendance/services.py (check-in/out IP logging)
  - app/core/audit.py (security audit log IP logging)

Caveat: X-Forwarded-For is trivially spoofable by anyone calling the
API directly (not through the proxy) unless Render is configured to
only accept inbound traffic from Vercel's IP ranges. That's a
defense-in-depth improvement worth doing separately; this helper alone
fixes the "everyone shares one IP" correctness bug, not spoofing.
"""

from fastapi import Request


def get_client_ip(request: Request | None) -> str | None:
    if not request:
        return None
    # Behind a proxy, the real client IP is the first hop in
    # X-Forwarded-For (each proxy in the chain appends its own hop after
    # the original client's IP, so the first entry is the one we want).
    # Falls back to the direct connection for non-proxied deployments
    # (e.g. local dev, or a same-domain deployment with no proxy at all).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
