"""
Dynamic sidebar generation.

The frontend must not decide what a role can see — the brief is explicit
that "no frontend hardcoding" should exist for role → menu mapping. This
module builds the sidebar entirely from data already in the database:

    role's permissions (role_permissions -> permissions.module)
        + modules table (label/icon/route/order for each module_key)
        + always_visible modules (Dashboard, Profile — every
          authenticated user gets these regardless of permissions)

Adding/removing a sidebar item for a role is therefore a permissions
change (grant/revoke a row in role_permissions), not a code change.

SUPER ADMIN is a special case: app/core/rbac.py already treats it as
having every permission implicitly (rows are never seeded for it), so
it's given every module here too rather than only the always_visible
ones.
"""

from app.core.constants import ADMIN
from app.core.database import supabase_admin


def _all_modules() -> list[dict]:
    response = (
        supabase_admin.table("modules")
        .select("module_key, label, icon, route, sort_order, always_visible")
        .order("sort_order")
        .execute()
    )

    return response.data or []


def _role_permission_modules(role_id: str) -> set[str]:
    """Distinct `permissions.module` values the given role has access to."""

    response = (
        supabase_admin.table("role_permissions")
        .select("permissions!inner(module)")
        .eq("role_id", role_id)
        .execute()
    )

    return {
        row["permissions"]["module"]
        for row in (response.data or [])
        if row.get("permissions") and row["permissions"].get("module")
    }


def build_sidebar(role_name: str, role_id: str) -> list[dict]:
    """
    Returns the ordered list of sidebar entries the given role should see,
    each as {module_key, label, icon, route}.
    """

    modules = _all_modules()

    if role_name == ADMIN:
        visible_keys = {m["module_key"] for m in modules}
    else:
        visible_keys = _role_permission_modules(role_id)

        for m in modules:
            if m["always_visible"]:
                visible_keys.add(m["module_key"])

    return [
        {
            "key": m["module_key"],
            "label": m["label"],
            "icon": m["icon"],
            "route": m["route"],
        }
        for m in modules
        if m["module_key"] in visible_keys
    ]


def allowed_module_keys(role_name: str, role_id: str) -> list[str]:
    """Flat list of module keys the role can access (for `allowed_modules`)."""

    return [entry["key"] for entry in build_sidebar(role_name, role_id)]
