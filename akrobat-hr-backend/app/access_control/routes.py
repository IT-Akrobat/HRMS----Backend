from fastapi import APIRouter, Depends

from app.access_control.schemas import UpdateAccessControlSettings
from app.access_control.services import (
    force_logout_all_admins,
    get_access_control_settings,
    list_locked_accounts,
    unlock_account,
    update_access_control_settings,
)
from app.core.audit import record_audit_log
from app.core.messages import UPDATED
from app.core.permissions import require_role
from app.core.responses import success_response

router = APIRouter(prefix="/access-control", tags=["Access Control"])


# =========================
# GET ACCESS CONTROL SETTINGS
# =========================


@router.get("/")
def get_settings(user=Depends(require_role(["SUPER ADMIN"]))):
    return success_response(
        message="Access control settings fetched successfully",
        data=get_access_control_settings(),
    )


# =========================
# UPDATE ACCESS CONTROL SETTINGS
# =========================


@router.put("/")
def update_settings(
    data: UpdateAccessControlSettings, user=Depends(require_role(["SUPER ADMIN"]))
):
    updated = update_access_control_settings(data.model_dump(exclude_unset=True))

    record_audit_log(
        module="SETTINGS",
        action="UPDATE_ACCESS_CONTROL",
        performed_by=user.id,
        description="Updated access control settings",
    )

    return success_response(message=UPDATED, data=updated)


# =========================
# FORCE LOGOUT ALL ADMINS
# =========================


@router.post("/force-logout-all")
def force_logout_all(user=Depends(require_role(["SUPER ADMIN"]))):
    result = force_logout_all_admins()

    record_audit_log(
        module="SETTINGS",
        action="FORCE_LOGOUT_ALL",
        performed_by=user.id,
        description=f"Force-logged-out {result.get('signed_out', 0)} admin session(s)",
    )

    return success_response(message="Admins signed out", data=result)


# =========================
# LOCKED ACCOUNTS
# =========================


@router.get("/lockouts")
def get_locked_accounts(user=Depends(require_role(["SUPER ADMIN"]))):
    return success_response(
        message="Locked accounts fetched successfully",
        data=list_locked_accounts(),
    )


@router.post("/lockouts/{employee_id}/unlock")
def unlock_locked_account(
    employee_id: str, user=Depends(require_role(["SUPER ADMIN"]))
):
    employee = unlock_account(employee_id)

    record_audit_log(
        module="SETTINGS",
        action="UNLOCK_ACCOUNT",
        performed_by=user.id,
        description=f"Unlocked account for {employee.get('full_name') or employee_id}",
    )

    return success_response(message="Account unlocked", data=employee)
