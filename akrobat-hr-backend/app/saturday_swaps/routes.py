from fastapi import APIRouter, Depends, Query, Request

from app.core.rbac import require_permission
from app.core.security import get_current_user
from app.saturday_swaps.schemas import (
    CreateSaturdaySwapRequest,
    UpdateSaturdaySwapStatusRequest,
)
from app.saturday_swaps.services import (
    apply_saturday_swap,
    cancel_swap,
    get_all_swaps,
    get_my_swaps,
    get_swap_options,
    get_swaps_to_decide,
    update_swap_status,
)

router = APIRouter(prefix="/saturday-swaps", tags=["Saturday Swaps"])


# NOTE: fixed paths (/my, /options, /team, /all) are declared before the
# "/{swap_id}" routes so they are never swallowed by the path parameter.


@router.post("/")
def create_swap(
    data: CreateSaturdaySwapRequest,
    request: Request,
    user=Depends(get_current_user),
):
    return apply_saturday_swap(user.id, data, request=request)


@router.get("/options")
def swap_options(user=Depends(get_current_user)):
    return get_swap_options(user.id)


@router.get("/my")
def my_swaps(user=Depends(get_current_user)):
    return get_my_swaps(user.id)


@router.get("/team")
def team_swaps(user=Depends(get_current_user)):
    # Scoped inside the service to employees this caller is the approver for.
    return get_swaps_to_decide(user.id)


@router.get("/all")
def all_swaps(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(require_permission("VIEW_LEAVE_REQUESTS")),
):
    return get_all_swaps(user.id, status=status, page=page, limit=limit)


@router.put("/{swap_id}/cancel")
def cancel(swap_id: str, request: Request, user=Depends(get_current_user)):
    return cancel_swap(swap_id, user.id, request=request)


@router.put("/{swap_id}")
def decide(
    swap_id: str,
    data: UpdateSaturdaySwapStatusRequest,
    request: Request,
    user=Depends(get_current_user),
):
    return update_swap_status(swap_id, data, auth_user_id=user.id, request=request)
