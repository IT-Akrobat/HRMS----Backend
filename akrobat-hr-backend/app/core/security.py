from fastapi import Request

from app.access_control.services import is_session_invalidated
from app.core.config import ACCESS_TOKEN_COOKIE
from app.core.database import supabase
from app.core.exceptions import unauthorized


def get_current_user(request: Request):
    # Access token now travels as an httpOnly cookie (see
    # app/core/cookies.py) instead of an `Authorization: Bearer ...`
    # header -- the frontend no longer holds the token in JS at all, so
    # it has nothing to put in a header. FastAPI's HTTPBearer is gone
    # for the same reason; this reads the cookie directly off the
    # request instead.
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)

    if not token:
        unauthorized("Invalid or expired token.")

    try:

        response = supabase.auth.get_user(token)

        if not response.user:
            unauthorized("Invalid or expired token.")

        # Real enforcement for Access Control > Force logout all (see
        # app/access_control/services.py). A revoked refresh token alone
        # doesn't stop an already-issued access token from continuing to
        # validate here, so without this check a force-logged-out user
        # stays logged in until their token's natural expiry.
        if is_session_invalidated(response.user.id):
            unauthorized(
                "Your session was ended by an administrator. Please log in again."
            )

        return response.user

    except Exception as e:
        print("SUPABASE AUTH ERROR:", e)
        unauthorized("Invalid or expired token.")


def get_token_from_cookie(request: Request) -> str | None:
    """Small helper for the few call sites (e.g. the WS handshakes in
    app/main.py) that need the raw token rather than the resolved user."""
    return request.cookies.get(ACCESS_TOKEN_COOKIE)
