"""
httpOnly cookie helpers for the access/refresh tokens, plus the
double-submit CSRF cookie.

Why this exists: the tokens used to be returned in the /auth/login JSON
body and stored in the frontend's localStorage (see git history /
authService.js). That means any XSS anywhere on the page -- this app or
a compromised third-party script -- can read localStorage and steal a
live session, refresh token included. httpOnly cookies aren't readable
by JS at all, so the same XSS bug becomes far less damaging (no token
exfiltration, though DOM-based damage/UI manipulation is still possible
-- cookies aren't a fix for XSS, just for *this specific* blast radius).

Trade-off: cookies are sent automatically by the browser on *every*
request to this origin, including ones a malicious third-party site
triggers (CSRF). That's what app/core/csrf.py's double-submit check is
for -- don't remove the cookie helpers here without keeping that too.
"""

import secrets

from fastapi import Response

from app.core.config import (
    ACCESS_TOKEN_COOKIE,
    COOKIE_DOMAIN,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    CSRF_COOKIE,
    REFRESH_TOKEN_COOKIE,
)

# Supabase access tokens are ~1hr; give the cookie a little headroom over
# that so a clock skew or slow request doesn't drop it early. The access
# token itself is still what's actually validated server-side on every
# request (see app/core/security.py) -- this is just how long the
# browser holds onto the cookie.
ACCESS_TOKEN_MAX_AGE = 60 * 70  # 70 minutes
# Supabase refresh tokens are long-lived; 30 days is a reasonable ceiling
# for "stay logged in" without being forever. Force logout / access
# control's session invalidation (see app/access_control/services.py)
# still overrides this at request time regardless of cookie age.
REFRESH_TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _cookie_kwargs(max_age: int, http_only: bool) -> dict:
    return dict(
        max_age=max_age,
        httponly=http_only,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path="/",
    )


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_TOKEN_COOKIE, access_token, **_cookie_kwargs(ACCESS_TOKEN_MAX_AGE, True)
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        **_cookie_kwargs(REFRESH_TOKEN_MAX_AGE, True),
    )


def issue_csrf_cookie(response: Response) -> str:
    """
    Double-submit CSRF pattern: this cookie is deliberately NOT httpOnly
    -- the frontend reads it via document.cookie and echoes it back as
    the X-CSRF-Token header on every mutating request (see
    apiClient.js). A cross-site attacker can trigger the browser to send
    the cookie automatically, but can't read it (browsers block
    cross-origin cookie reads) and so can't produce a matching header,
    which is what app/core/csrf.py checks.
    """
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, token, **_cookie_kwargs(REFRESH_TOKEN_MAX_AGE, False)
    )
    return token


def clear_auth_cookies(response: Response) -> None:
    for name in (ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name,
            domain=COOKIE_DOMAIN,
            path="/",
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
        )
