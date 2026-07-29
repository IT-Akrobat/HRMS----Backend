from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.access_control.services import is_session_invalidated
from app.core.database import supabase
from app.core.exceptions import unauthorized

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

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
