"""
Permission-based RBAC.

The schema already has roles / permissions / role_permissions tables, but
nothing in the app used them — every route was locked with `require_role`
(a hardcoded list of role names). That works, but it means adding a new
role or tweaking who can approve leave requires a code change + deploy.

This module adds a second dependency, `require_permission`, that checks
the *permission* (e.g. "APPROVE_LEAVE") a user's role actually has,
looked up from the database. `require_role` still exists and is fine for
simple super-admin-only endpoints, but new/updated routes should prefer
`require_permission` so RBAC is data-driven, matching the "Do NOT hardcode
permissions" requirement in the architecture spec.

SUPER ADMIN always passes, regardless of explicit permission rows, since
that role is meant to have full access.
"""

from fastapi import Depends

from app.core.constants import ADMIN
from app.core.database import supabase_admin
from app.core.exceptions import forbidden, unauthorized
from app.core.security import get_current_user


def _get_role_for_user(auth_user_id: str) -> tuple[str, str]:
    """Returns (role_id, role_name) for the given auth user."""

    response = (
        supabase_admin.table("user_profiles")
        .select("role_id, roles(role_name)")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        unauthorized("User profile not found.")

    role_data = response.data.get("roles")
    role_id = response.data.get("role_id")

    if not role_data or not role_id:
        forbidden("Role not assigned.")

    return role_id, role_data.get("role_name")


def _role_has_permission(role_id: str, permission_name: str) -> bool:
    response = (
        supabase_admin.table("role_permissions")
        .select("permission_id, permissions!inner(permission_name)")
        .eq("role_id", role_id)
        .eq("permissions.permission_name", permission_name)
        .execute()
    )

    return bool(response.data)


def require_permission(permission_name: str):
    """
    FastAPI dependency: allow the request only if the caller's role has
    been granted `permission_name` in role_permissions, or the caller is
    SUPER ADMIN.

    Example:
        @router.post("/", dependencies=[Depends(require_permission("CREATE_EMPLOYEE"))])
    """

    def permission_checker(user=Depends(get_current_user)):
        role_id, role_name = _get_role_for_user(user.id)

        if role_name == ADMIN:
            return user

        if not _role_has_permission(role_id, permission_name):
            forbidden(f"You don't have permission to perform this action ({permission_name}).")

        return user

    return permission_checker


def get_role_name(auth_user_id: str) -> str:
    """Returns just the role name for the given auth user (e.g. for
    ownership-vs-permission checks inside a service, not as a route
    dependency)."""

    _, role_name = _get_role_for_user(auth_user_id)
    return role_name


def has_permission(auth_user_id: str, permission_name: str) -> bool:
    """
    Non-dependency version of the require_permission check, for services
    that need to decide "is this a full HR-style view, or should I scope
    the query down to the caller's own records" rather than a hard
    allow/deny at the route level.
    """

    role_id, role_name = _get_role_for_user(auth_user_id)

    if role_name == ADMIN:
        return True

    return _role_has_permission(role_id, permission_name)


def get_permissions_for_role(role_id: str, role_name: str) -> list[str]:
    """
    Full list of permission_name values granted to a role, for surfacing
    in GET /auth/me. SUPER ADMIN implicitly holds every permission in the
    system (see the module docstring / require_permission above), so it
    is expanded to the full permissions table rather than whatever rows
    happen to exist in role_permissions for it (there normally are none).
    """

    if role_name == ADMIN:
        response = supabase_admin.table("permissions").select("permission_name").execute()

        return sorted({row["permission_name"] for row in (response.data or [])})

    response = (
        supabase_admin.table("role_permissions")
        .select("permissions!inner(permission_name)")
        .eq("role_id", role_id)
        .execute()
    )

    return sorted(
        {
            row["permissions"]["permission_name"]
            for row in (response.data or [])
            if row.get("permissions")
        }
    )


def require_any_permission(permission_names: list[str]):
    """Allow the request if the caller's role has ANY of the listed permissions."""

    def permission_checker(user=Depends(get_current_user)):
        role_id, role_name = _get_role_for_user(user.id)

        if role_name == ADMIN:
            return user

        if not any(_role_has_permission(role_id, p) for p in permission_names):
            forbidden("You don't have permission to perform this action.")

        return user

    return permission_checker
