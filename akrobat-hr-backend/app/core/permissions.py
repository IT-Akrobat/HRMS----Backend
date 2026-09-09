from fastapi import Depends

from app.core.database import supabase_admin
from app.core.exceptions import forbidden, unauthorized
from app.core.security import get_current_user


def require_role(allowed_roles: list[str]):

    def role_checker(
        user=Depends(get_current_user),
    ):

        response = supabase_admin.table("user_profiles").select("""
                role_id,
                roles(
                    role_name
                )
                """).eq("auth_user_id", user.id).single().execute()

        if not response.data:
            unauthorized("User profile not found.")

        role_data = response.data.get("roles")

        if not role_data:
            forbidden("Role not assigned.")

        role_name = role_data.get("role_name")

        if role_name not in allowed_roles:
            forbidden("You don't have permission to perform this action.")

        return user

    return role_checker


def get_role_name_for_auth_user(auth_user_id: str) -> str | None:
    """Looks up the role name for a given Supabase auth user id, e.g.
    "SUPER ADMIN". Unlike require_role(), this never raises/forbids --
    it's for read paths that need to branch their response by role
    (e.g. Super Admin sees more than everyone else) rather than block
    access outright. Returns None (never raises) if the user has no
    linked profile or no role assigned, so callers should treat that
    the same as "not Super Admin"/"most restricted view".
    """

    try:
        response = (
            supabase_admin.table("user_profiles")
            .select("roles(role_name)")
            .eq("auth_user_id", auth_user_id)
            .maybe_single()
            .execute()
        )

        if not response or not response.data:
            return None

        role_data = response.data.get("roles")

        return role_data.get("role_name") if role_data else None

    except Exception:
        return None
