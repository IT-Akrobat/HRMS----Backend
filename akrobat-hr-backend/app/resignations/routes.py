from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.core.constants import ADMIN
from app.core.permissions import require_role
from app.resignations import services
from app.resignations.schemas import ResignationCreate, ResignationUpdate

# Every endpoint is SUPER ADMIN only (hard role check, same pattern as
# employee creation). HR Admin / Manager / Employee get 403.
router = APIRouter(prefix="/resigned-employees", tags=["Resigned Employees"])

super_admin_only = require_role([ADMIN])


@router.get("/")
def list_resigned(
    status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    user=Depends(super_admin_only),
):
    return services.list_resignations(status, department, year, search)


@router.post("/")
def mark_resigned(
    data: ResignationCreate,
    request: Request,
    user=Depends(super_admin_only),
):
    return services.mark_resigned(data, user, request)


@router.get("/{employee_id}")
def get_one(employee_id: str, user=Depends(super_admin_only)):
    return services.get_resignation(employee_id)


@router.patch("/{employee_id}")
def update_one(
    employee_id: str,
    data: ResignationUpdate,
    request: Request,
    user=Depends(super_admin_only),
):
    return services.update_resignation(employee_id, data, user, request)


@router.post("/{employee_id}/relieve")
def relieve(employee_id: str, request: Request, user=Depends(super_admin_only)):
    return services.relieve_now(employee_id, user, request)


@router.post("/{employee_id}/withdraw")
def withdraw(employee_id: str, request: Request, user=Depends(super_admin_only)):
    return services.withdraw_resignation(employee_id, user, request)


# ---- read-only tabs ------------------------------------------------------


@router.get("/{employee_id}/profile")
def profile(employee_id: str, user=Depends(super_admin_only)):
    return services.get_profile_tab(employee_id)


@router.get("/{employee_id}/attendance")
def attendance(
    employee_id: str,
    month: Optional[str] = Query(None, description="YYYY-MM"),
    status: Optional[str] = Query(None),
    user=Depends(super_admin_only),
):
    return services.get_attendance_tab(employee_id, month, status)


@router.get("/{employee_id}/leaves")
def leaves(employee_id: str, user=Depends(super_admin_only)):
    return services.get_leaves_tab(employee_id)


@router.get("/{employee_id}/payroll")
def payroll(employee_id: str, user=Depends(super_admin_only)):
    return services.get_payroll_tab(employee_id)


@router.get("/{employee_id}/documents")
def documents(employee_id: str, user=Depends(super_admin_only)):
    return services.get_documents_tab(employee_id)


@router.get("/{employee_id}/audit-trail")
def audit_trail(employee_id: str, user=Depends(super_admin_only)):
    return services.get_audit_tab(employee_id)
