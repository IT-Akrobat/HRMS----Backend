from fastapi import APIRouter, Depends, Query, Request

from app.payroll.schemas import CreatePayrollRequest, UpdatePayrollRequest

from app.payroll.services import (
    create_payroll,
    get_payrolls,
    get_my_payrolls,
    get_payroll,
    update_payroll,
    delete_payroll,
)

from app.core.security import get_current_user
from app.core.rbac import require_permission

router = APIRouter(prefix="/payroll", tags=["Payroll"])


# ==========================================
# CREATE PAYROLL (HR / Admin only)
# ==========================================


@router.post("/")
def create(
    data: CreatePayrollRequest,
    request: Request,
    user=Depends(require_permission("CREATE_PAYROLL")),
):
    return create_payroll(data, current_user=user, request=request)


# ==========================================
# GET ALL PAYROLL (HR / Admin only — full company view)
# ==========================================


@router.get("/")
def get_all(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user=Depends(require_permission("VIEW_PAYROLL")),
):
    return get_payrolls(page=page, limit=limit)


# ==========================================
# GET MY PAYROLL (self-service — any authenticated employee, own records only)
# ==========================================


@router.get("/my")
def get_my(user=Depends(get_current_user)):
    return get_my_payrolls(user.id)


# ==========================================
# GET ONE PAYROLL (HR/Admin, or the owning employee)
# ==========================================


@router.get("/{payroll_id}")
def get_one(payroll_id: str, user=Depends(get_current_user)):
    return get_payroll(payroll_id, auth_user_id=user.id)


# ==========================================
# UPDATE PAYROLL (HR / Admin only)
# ==========================================


@router.put("/{payroll_id}")
def update(
    payroll_id: str,
    data: UpdatePayrollRequest,
    request: Request,
    user=Depends(require_permission("EDIT_PAYROLL")),
):
    return update_payroll(payroll_id, data, current_user=user, request=request)


# ==========================================
# DELETE PAYROLL (HR / Admin only)
# ==========================================


@router.delete("/{payroll_id}")
def delete(
    payroll_id: str,
    request: Request,
    user=Depends(require_permission("DELETE_PAYROLL")),
):
    return delete_payroll(payroll_id, current_user=user, request=request)
