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
