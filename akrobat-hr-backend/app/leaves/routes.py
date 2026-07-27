from fastapi import APIRouter, Depends, Query, Request

from app.leaves.schemas import CreateLeaveRequest, UpdateLeaveStatusRequest

from app.leaves.services import (
    apply_leave,
    get_my_leaves,
    get_all_leaves,
    get_team_leaves,
    update_leave_status,
)

from app.core.security import get_current_user
from app.core.rbac import require_permission
from app.core.permissions import require_role
from app.core.constants import ADMIN

router = APIRouter(prefix="/leaves", tags=["Leaves"])


# ==========================================
# APPLY LEAVE (self-service — any authenticated employee)
# ==========================================


@router.post("/")
def create_leave(data: CreateLeaveRequest, request: Request, user=Depends(get_current_user)):
    return apply_leave(user.id, data, request=request)


# ==========================================
# GET MY LEAVES (self-service — own records only)
# ==========================================


@router.get("/my")
def my_leaves(user=Depends(get_current_user)):
    return get_my_leaves(user.id)


# ==========================================
# GET TEAM LEAVES (Manager / HR — view only, direct + indirect reports)
# ==========================================


@router.get("/team")
def team_leaves(user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))):
    return get_team_leaves(user.id)


# ==========================================
# GET ALL LEAVES (HR / Admin only — company-wide view)
# ==========================================


@router.get("/")
def all_leaves(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    user=Depends(require_permission("VIEW_LEAVE_REQUESTS")),
):
    return get_all_leaves(page=page, limit=limit, status=status)


# ==========================================
# APPROVE / REJECT LEAVE
# (SUPER ADMIN only — company policy: no other role may approve/reject
#  leave, regardless of what's granted in role_permissions)
# ==========================================


@router.put("/{leave_id}")
def update_status(
    leave_id: str,
    data: UpdateLeaveStatusRequest,
    request: Request,
    user=Depends(require_role([ADMIN])),
):
    return update_leave_status(leave_id, data, auth_user_id=user.id, request=request)
