"""
CSRF protection for the cookie-based auth flow.

Once auth moved from "Bearer token the frontend attaches on purpose" to
"httpOnly cookie the browser attaches automatically" (see
app/core/cookies.py), every mutating endpoint became reachable by a
forged cross-site request that just points a <form> or fetch() at this
API -- the browser will happily attach the cookies for a logged-in user.
CORS does NOT stop this: CORS only blocks the attacker's JS from
*reading the response*, not the browser from *sending the request*.

Standard fix: double-submit cookie. /auth/login (and /auth/refresh) also
set a second, non-httpOnly cookie holding a random CSRF token. The
frontend reads that cookie with JS and echoes it back as a custom
header on every mutating call. A same-site page can do that (it can
read its own cookies); a cross-site attacker's page cannot (browsers
block cross-origin `document.cookie` reads of another site's cookies),
so it can't produce a matching header even though it can make the
browser send the cookie itself.

Applied as global middleware (rather than a per-route dependency) so
every POST/PUT/PATCH/DELETE across every router is covered by default,
including ones added later -- nobody has to remember to add a
dependency to a new route.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import CSRF_COOKIE, CSRF_HEADER

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints reachable before a CSRF cookie exists yet (no session to
# forge a request against) or that intentionally don't run through the
# cookie/CSRF flow. Keep this list short and explicit.
EXEMPT_PATHS = {
    "/auth/login",
}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in UNSAFE_METHODS and request.url.path not in EXEMPT_PATHS:
            cookie_token = request.cookies.get(CSRF_COOKIE)
            header_token = request.headers.get(CSRF_HEADER)

            if not cookie_token or not header_token or cookie_token != header_token:
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "status_code": 403,
                        "message": "CSRF token missing or invalid.",
                        "errors": None,
                    },
                )

        return await call_next(request)
