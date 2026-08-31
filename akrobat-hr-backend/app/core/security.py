from types import SimpleNamespace

import jwt
from fastapi import HTTPException, Request

from app.access_control.services import is_session_invalidated
from app.core.config import ACCESS_TOKEN_COOKIE, SUPABASE_JWT_SECRET, SUPABASE_URL
from app.core.exceptions import unauthorized

# ---------------------------------------------------------------------
# Supabase projects that have moved to (or were created with) JWT
# Signing Keys issue access tokens signed with an asymmetric algorithm
# (ES256 by default, sometimes RS256) instead of the legacy shared-secret
# HS256. Those tokens can only be verified against the project's public
# JWKS, not SUPABASE_JWT_SECRET -- that's the "specified alg value is
# not allowed" error PyJWT raises when a non-HS256 token hits
# algorithms=["HS256"].
#
# PyJWKClient fetches + caches that public key set (keyed by the
# token's `kid`) so verification still happens locally, no per-request
# call to the Supabase Auth API. We branch on the token's own `alg`
# header so both legacy HS256 tokens (if the project still issues them)
# and new asymmetric ones keep working side by side.
# ---------------------------------------------------------------------
_jwks_client = jwt.PyJWKClient(
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True
)


def _decode_supabase_jwt(token: str) -> dict:
    alg = jwt.get_unverified_header(token).get("alg", "HS256")

    if alg == "HS256":
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )

    signing_key = _jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[alg],
        audience="authenticated",
    )


def get_current_user(request: Request):
    # Access token travels as an httpOnly cookie (see app/core/cookies.py).
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)

    if not token:
        unauthorized("Invalid or expired token.")

    try:
        payload = _decode_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        unauthorized("Invalid or expired token.")
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
        print("JWT VERIFY ERROR:", e)
        unauthorized("Invalid or expired token.")

    user_id = payload.get("sub")
    if not user_id:
        unauthorized("Invalid or expired token.")

    # Force-logout check -- DB lookup via PostgREST, not the Auth API.
    try:
        if is_session_invalidated(user_id):
            unauthorized(
                "Your session was ended by an administrator. Please log in again."
            )
    except HTTPException:
        raise
    except Exception as e:
        print("SESSION INVALIDATION CHECK WARNING:", e)

    return SimpleNamespace(id=user_id, email=payload.get("email"))


def verify_access_token(token: str) -> SimpleNamespace | None:
    """Same local JWT verification as get_current_user, but returns None
    on failure instead of raising -- used by the WebSocket handshakes in
    app/main.py, which can't use a FastAPI Depends()."""
    if not token:
        return None

    try:
        payload = _decode_supabase_jwt(token)
    except (jwt.InvalidTokenError, jwt.PyJWKClientError):
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    return SimpleNamespace(id=user_id, email=payload.get("email"))


def get_token_from_cookie(request: Request) -> str | None:
    """Small helper for call sites that need the raw token rather than
    the resolved user."""
    return request.cookies.get(ACCESS_TOKEN_COOKIE)
