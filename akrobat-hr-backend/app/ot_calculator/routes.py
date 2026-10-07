from fastapi import APIRouter, Depends, Query, Request

from app.core.rbac import require_permission
from app.ot_calculator.schemas import SaveOtAdjustmentsRequest
from app.ot_calculator.services import get_ot_month, save_ot_adjustments

router = APIRouter(prefix="/ot-calculator", tags=["OT Calculator"])


@router.get("/month")
def ot_month(
    month: str = Query(..., description="YYYY-MM"),
    employee_id: str | None = Query(None),
    user=Depends(require_permission("VIEW_ALL_ATTENDANCE")),
):
    return get_ot_month(month, employee_id)


@router.put("/adjustments")
def ot_save_adjustments(
    data: SaveOtAdjustmentsRequest,
    request: Request,
    user=Depends(require_permission("VIEW_ALL_ATTENDANCE")),
):
    return save_ot_adjustments(data, user, request)
