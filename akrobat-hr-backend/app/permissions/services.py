"""
Backs the Super Admin "Permissions" screen — a node-graph editor where
role nodes on one side connect to permission nodes on the other. Every
edge in that graph is one row in `role_permissions`.

SUPER ADMIN is intentionally excluded from the editable graph: it
bypasses `require_permission`/`require_role` checks everywhere else in
the app (see app/core/rbac.py), so drawing or removing edges for it
would be cosmetic only and misleading. The matrix response still lists
it, flagged `is_super_admin: true` with every permission implicitly
granted, so the UI can render it as a node without offering edit
affordances on it.
"""

from app.core.audit import record_audit_log
from app.core.constants import ADMIN
from app.core.database import supabase_admin
from app.core.exceptions import bad_request, not_found
from app.core.messages import NOT_FOUND

# =========================
# GET ALL PERMISSIONS (grouped by module, for the right-hand column)
# =========================


def get_all_permissions():
    response = (
        supabase_admin.table("permissions")
        .select("*")
        .order("module")
        .order("permission_name")
        .execute()
    )

    return response.data or []


# =========================
# GET FULL GRAPH: roles, permissions, and the edges between them
# =========================


def get_permission_matrix():
    roles_res = supabase_admin.table("roles").select("*").order("role_name").execute()
    permissions_res = (
        supabase_admin.table("permissions")
        .select("*")
        .order("module")
        .order("permission_name")
        .execute()
    )

    roles = roles_res.data or []
    permissions = permissions_res.data or []

    role_ids = [r["id"] for r in roles if r.get("role_name") != ADMIN]

    grants = []
    if role_ids:
        grants_res = (
            supabase_admin.table("role_permissions")
            .select("role_id, permission_id")
            .in_("role_id", role_ids)
            .execute()
        )
        grants = grants_res.data or []

    # SUPER ADMIN holds every permission implicitly (see module docstring)
    # — expand that out into synthetic edges so the graph renders it fully
    # connected without a real role_permissions row backing each line.
    super_admin = next((r for r in roles if r.get("role_name") == ADMIN), None)
    if super_admin:
        grants = grants + [
            {"role_id": super_admin["id"], "permission_id": p["id"]}
            for p in permissions
        ]

    roles_out = [{**r, "is_super_admin": r.get("role_name") == ADMIN} for r in roles]

    return {
        "roles": roles_out,
        "permissions": permissions,
        "grants": grants,
    }


# =========================
# INTERNAL: load + guard a role, blocking edits to SUPER ADMIN
# =========================


def _get_editable_role(role_id: str) -> dict:
    response = (
        supabase_admin.table("roles")
        .select("*")
        .eq("id", role_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        not_found(NOT_FOUND)

    role = response.data

    if role.get("role_name") == ADMIN:
        bad_request(
            "SUPER ADMIN already has every permission implicitly and can't be edited."
        )

    return role


# =========================
# GRANT — draw one edge
# =========================


def grant_permission(role_id: str, permission_id: str, performed_by: str | None):
    role = _get_editable_role(role_id)

    permission_res = (
        supabase_admin.table("permissions")
        .select("*")
        .eq("id", permission_id)
        .maybe_single()
        .execute()
    )

    if not permission_res or not permission_res.data:
        not_found(NOT_FOUND)

    permission = permission_res.data

    supabase_admin.table("role_permissions").upsert(
        {"role_id": role_id, "permission_id": permission_id},
        on_conflict="role_id,permission_id",
    ).execute()

    record_audit_log(
        module="PERMISSIONS",
        action="GRANT",
        performed_by=performed_by,
        record_id=role_id,
        description=(
            f"Granted {permission['permission_name']} to role {role['role_name']}"
        ),
    )

    return {"role_id": role_id, "permission_id": permission_id, "granted": True}


# =========================
# REVOKE — remove one edge
# =========================


def revoke_permission(role_id: str, permission_id: str, performed_by: str | None):
    role = _get_editable_role(role_id)

    permission_res = (
        supabase_admin.table("permissions")
        .select("*")
        .eq("id", permission_id)
        .maybe_single()
        .execute()
    )

    if not permission_res or not permission_res.data:
        not_found(NOT_FOUND)

    permission = permission_res.data

    supabase_admin.table("role_permissions").delete().eq("role_id", role_id).eq(
        "permission_id", permission_id
    ).execute()

    record_audit_log(
        module="PERMISSIONS",
        action="REVOKE",
        performed_by=performed_by,
        record_id=role_id,
        description=(
            f"Revoked {permission['permission_name']} from role {role['role_name']}"
        ),
    )

    return {"role_id": role_id, "permission_id": permission_id, "granted": False}


# =========================
# BULK REPLACE — save a role node's full set of connections at once
# =========================


def set_role_permissions(
    role_id: str, permission_ids: list[str], performed_by: str | None
):
    role = _get_editable_role(role_id)

    existing_res = (
        supabase_admin.table("role_permissions")
        .select("permission_id")
        .eq("role_id", role_id)
        .execute()
    )
    existing_ids = {row["permission_id"] for row in (existing_res.data or [])}
    new_ids = set(permission_ids)

    to_add = new_ids - existing_ids
    to_remove = existing_ids - new_ids

    if to_add:
        supabase_admin.table("role_permissions").upsert(
            [{"role_id": role_id, "permission_id": pid} for pid in to_add],
            on_conflict="role_id,permission_id",
        ).execute()

    if to_remove:
        supabase_admin.table("role_permissions").delete().eq("role_id", role_id).in_(
            "permission_id", list(to_remove)
        ).execute()

    if to_add or to_remove:
        record_audit_log(
            module="PERMISSIONS",
            action="UPDATE",
            performed_by=performed_by,
            record_id=role_id,
            description=f"Updated permissions for role {role['role_name']}",
            new_values={
                "added": len(to_add),
                "removed": len(to_remove),
            },
        )

    return {
        "role_id": role_id,
        "permission_ids": sorted(new_ids),
        "added": len(to_add),
        "removed": len(to_remove),
    }
