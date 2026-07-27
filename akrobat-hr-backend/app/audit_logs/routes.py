from fastapi import APIRouter, Depends, Query, Request

from app.audit_logs.schemas import CreateAuditLogRequest

from app.audit_logs.services import (
    create_audit_log,
    get_audit_logs,
    get_audit_log,
    get_employee_logs,
    get_module_logs,
    get_action_logs,
    get_logs_by_date,
    delete_audit_log,
)

from app.core.rbac import require_permission

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


# ==========================================
# CREATE LOG (manual/system entry — SUPER ADMIN only)
# ==========================================


@router.post("/")
def create(
    data: CreateAuditLogRequest,
    request: Request,
    user=Depends(require_permission("MANAGE_AUDIT_LOGS")),
):
    return create_audit_log(user.id, data, request=request)


# ==========================================
# GET ALL LOGS (HR / Admin only — company-wide)
# ==========================================


@router.get("/")
def get_all(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_permission("VIEW_AUDIT_LOGS")),
):
    return get_audit_logs(page=page, limit=limit)


# ==========================================
# LOGS BY EMPLOYEE (actor) / MODULE / ACTION / DATE — all HR / Admin only
# (registered before "/{log_id}" so these prefixed paths aren't shadowed)
# ==========================================


@router.get("/employee/{employee_id}")
def employee_logs(
    employee_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_permission("VIEW_AUDIT_LOGS")),
):
    return get_employee_logs(employee_id, page=page, limit=limit)


@router.get("/module/{module}")
def module_logs(
    module: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_permission("VIEW_AUDIT_LOGS")),
):
    return get_module_logs(module, page=page, limit=limit)


@router.get("/action/{action}")
def action_logs(
    action: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_permission("VIEW_AUDIT_LOGS")),
):
    return get_action_logs(action, page=page, limit=limit)


@router.get("/date/{log_date}")
def date_logs(log_date: str, user=Depends(require_permission("VIEW_AUDIT_LOGS"))):
    return get_logs_by_date(log_date)


# ==========================================
# GET SINGLE LOG
# ==========================================


@router.get("/{log_id}")
def get_one(log_id: str, user=Depends(require_permission("VIEW_AUDIT_LOGS"))):
    return get_audit_log(log_id)


# ==========================================
# DELETE LOG (SUPER ADMIN only)
# ==========================================


@router.delete("/{log_id}")
def delete(
    log_id: str,
    request: Request,
    user=Depends(require_permission("MANAGE_AUDIT_LOGS")),
):
    return delete_audit_log(log_id, auth_user_id=user.id, request=request)
