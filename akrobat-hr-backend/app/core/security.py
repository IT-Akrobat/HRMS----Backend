from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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

        return response.user

    except Exception as e:
        print("SUPABASE AUTH ERROR:", e)
        unauthorized("Invalid or expired token.")
