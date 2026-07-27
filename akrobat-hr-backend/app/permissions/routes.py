from fastapi import APIRouter, Depends

from app.core.messages import DELETED, UPDATED
from app.core.permissions import require_role
from app.core.responses import success_response
from app.permissions.schemas import PermissionGrant, RolePermissionsBulkUpdate
from app.permissions.services import (
    get_all_permissions,
    get_permission_matrix,
    grant_permission,
    revoke_permission,
    set_role_permissions,
)

router = APIRouter(prefix="/permissions", tags=["Permissions"])


# =========================
# LIST ALL PERMISSIONS (right-hand column of the graph)
# =========================


@router.get("/")
def all_permissions(user=Depends(require_role(["SUPER ADMIN"]))):
    return success_response(
        message="Permissions fetched successfully",
        data=get_all_permissions(),
    )


# =========================
# FULL GRAPH: roles + permissions + the edges between them
# =========================


@router.get("/matrix")
def permission_matrix(user=Depends(require_role(["SUPER ADMIN"]))):
    return success_response(
        message="Permission matrix fetched successfully",
        data=get_permission_matrix(),
    )


# =========================
# DRAW ONE EDGE (grant a permission to a role)
# =========================


@router.post("/grant")
def grant(
    payload: PermissionGrant,
    user=Depends(require_role(["SUPER ADMIN"])),
):
    result = grant_permission(payload.role_id, payload.permission_id, user.id)

    return success_response(message=UPDATED, data=result)


# =========================
# REMOVE ONE EDGE (revoke a permission from a role)
# =========================


@router.delete("/revoke/{role_id}/{permission_id}")
def revoke(
    role_id: str,
    permission_id: str,
    user=Depends(require_role(["SUPER ADMIN"])),
):
    result = revoke_permission(role_id, permission_id, user.id)

    return success_response(message=DELETED, data=result)


# =========================
# BULK REPLACE — save every connection for one role node at once
# =========================


@router.put("/roles/{role_id}")
def replace_role_permissions(
    role_id: str,
    payload: RolePermissionsBulkUpdate,
    user=Depends(require_role(["SUPER ADMIN"])),
):
    result = set_role_permissions(role_id, payload.permission_ids, user.id)

    return success_response(message=UPDATED, data=result)
