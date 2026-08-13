"""
Shared slowapi Limiter instance.

Lives in its own module (not app/main.py) so route files can import
`limiter` to decorate individual endpoints (e.g. @limiter.limit("5/minute")
on POST /auth/login) without creating a circular import with main.py,
which itself imports each router.
"""

from slowapi import Limiter

from app.core.request_ip import get_client_ip

# slowapi's built-in get_remote_address key_func reads request.client.host
# only -- the raw TCP connection. Behind the Vercel proxy (see
# app/core/request_ip.py for why that exists), that's Vercel's own IP for
# every single user, so the "5 attempts/minute" login limiter below would
# effectively rate-limit ALL users combined instead of each individually
# -- one busy minute of unrelated logins could lock everyone out. Use the
# same X-Forwarded-For-aware helper as the rest of the app instead.
limiter = Limiter(key_func=get_client_ip)
