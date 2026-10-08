"""
MC (medical leave) flow.

  Step 1  Employee applies for MC          -> leave manager + HR notified
                                              (see app/leaves/services.py apply_leave)
  Step 2  Employee attaches the certificate -> HR notified
  Then    HR validates the leave as MC      -> nothing more happens
          HR has NOT validated after 5 days -> HR, leave manager and Super Admin
                                              get a reminder (daily scheduler job)

leave_requests.mc_status: AWAITING_CERTIFICATE -> CERTIFICATE_UPLOADED -> VALIDATED
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, UploadFile

from app.core.audit import record_audit_log
from app.core.constants import ADMIN
from app.core.config import SUPABASE_DOCUMENTS_BUCKET
from app.core.database import supabase_admin
from app.core.exceptions import bad_request, forbidden, internal_server_error
from app.core.helpers.employee_helper import (
    get_employee_id_for_auth_user,
    get_employee_ids_for_role,
)
from app.core.logger import logger
from app.core.permissions import get_role_name_for_auth_user
from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.documents.services import _upload_to_storage, _validate_and_read_file
from app.leaves.services import (
    HR_ROLE_NAMES,
    get_hr_employee_ids,
    get_leave_manager_id,
)
from app.notifications.services import notify_employee

leave_repo = SupabaseRepository("leave_requests")
employee_repo = SupabaseRepository("employees")

MC_REMINDER_AFTER_DAYS = 5


def _get_mc_leave_or_error(leave_id: str) -> dict:
    leave = leave_repo.get_by_id_or_404(leave_id, "Leave request not found.")
    if not leave.get("mc_status"):
        bad_request("This leave request is not an MC.")
    return leave


def _is_hr_or_admin(auth_user_id: str) -> bool:
    role = get_role_name_for_auth_user(auth_user_id)
    return role == ADMIN or role in HR_ROLE_NAMES


# ==========================================
# STEP 2: EMPLOYEE ATTACHES THE MEDICAL CERTIFICATE
# ==========================================


def upload_medical_certificate(
    auth_user_id: str,
    leave_id: str,
    file: UploadFile,
    request: Optional[Request] = None,
):
    try:
        leave = _get_mc_leave_or_error(leave_id)
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id or employee_id != leave["employee_id"]:
            forbidden("You can only attach a certificate to your own MC.")

        if leave.get("mc_status") == "VALIDATED":
            bad_request("HR has already validated this MC.")

        content, ext, content_type = _validate_and_read_file(file)
        storage_path = _upload_to_storage(employee_id, content, ext, content_type)

        updated = leave_repo.update(
            leave_id,
            {
                "mc_certificate_path": storage_path,
                "mc_certificate_name": file.filename,
                "mc_uploaded_at": datetime.now(timezone.utc).isoformat(),
                "mc_status": "CERTIFICATE_UPLOADED",
            },
        )

        employee = employee_repo.get_by_id(employee_id, select="full_name") or {}
        name = employee.get("full_name", "An employee")
        for hr_id in get_hr_employee_ids():
            if hr_id != employee_id:
                notify_employee(
                    hr_id,
                    title="MC Certificate Uploaded",
                    message=(
                        f"{name} uploaded a medical certificate for MC "
                        f"({leave['start_date']} to {leave['end_date']}). "
                        "Please validate it."
                    ),
                    notification_type="LEAVE",
                )

        record_audit_log(
            module="LEAVE",
            action="MC_CERTIFICATE_UPLOADED",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=leave_id,
            description="Medical certificate attached",
            request=request,
        )

        return success_response(message="Medical certificate uploaded.", data=updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to upload the medical certificate.")


# ==========================================
# VIEW THE CERTIFICATE (owner, leave manager, HR, Super Admin)
# ==========================================


def get_medical_certificate_url(auth_user_id: str, leave_id: str):
    try:
        leave = _get_mc_leave_or_error(leave_id)
        if not leave.get("mc_certificate_path"):
            bad_request("No medical certificate has been uploaded yet.")

        viewer_id = get_employee_id_for_auth_user(auth_user_id)
        employee = employee_repo.get_by_id(
            leave["employee_id"], select="manager_id, leave_manager_id"
        )
        allowed = (
            viewer_id == leave["employee_id"]
            or (viewer_id and viewer_id == get_leave_manager_id(employee))
            or _is_hr_or_admin(auth_user_id)
        )
        if not allowed:
            forbidden("You don't have access to this certificate.")

        signed = supabase_admin.storage.from_(
            SUPABASE_DOCUMENTS_BUCKET
        ).create_signed_url(leave["mc_certificate_path"], 300)
        url = signed.get("signedURL") or signed.get("signedUrl")
        return success_response(
            message="Certificate link created.",
            data={"url": url, "file_name": leave.get("mc_certificate_name")},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to open the medical certificate.")


# ==========================================
# HR VALIDATES THE LEAVE AS MC
# ==========================================


def validate_mc(auth_user_id: str, leave_id: str, request: Optional[Request] = None):
    try:
        leave = _get_mc_leave_or_error(leave_id)

        if leave.get("mc_status") == "VALIDATED":
            bad_request("This MC is already validated.")
        if leave.get("mc_status") != "CERTIFICATE_UPLOADED":
            bad_request("The employee has not uploaded a medical certificate yet.")

        hr_employee_id = get_employee_id_for_auth_user(auth_user_id)
        updated = leave_repo.update(
            leave_id,
            {
                "mc_status": "VALIDATED",
                "mc_validated_by": hr_employee_id,
                "mc_validated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        notify_employee(
            leave["employee_id"],
            title="MC Validated",
            message=(
                f"HR has validated your MC ({leave['start_date']} to {leave['end_date']})."
            ),
            notification_type="LEAVE",
        )

        record_audit_log(
            module="LEAVE",
            action="MC_VALIDATED",
            performed_by=auth_user_id,
            target_employee_id=leave["employee_id"],
            record_id=leave_id,
            description="MC validated by HR",
            request=request,
        )

        return success_response(message="MC validated.", data=updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to validate the MC.")


# ==========================================
# DAILY JOB: MC NOT VALIDATED AFTER 5 DAYS
# ==========================================


def send_mc_validation_reminders() -> int:
    """
    For every MC that HR has not validated within 5 days of being applied,
    notify HR, the leave manager and Super Admin -- every day until HR
    validates it (rejected leaves are skipped).
    Registered as a daily job in app/main.py. Returns how many MCs were flagged.
    """

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=MC_REMINDER_AFTER_DAYS)
    ).isoformat()

    # Re-remind once per day: skip MCs already reminded in the last 20 hours
    # (the job runs once a day, so this only guards against double runs).
    recent = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()

    try:
        rows = (
            supabase_admin.table("leave_requests")
            .select(
                "id, employee_id, start_date, end_date, mc_status, applied_date, "
                "employees!leave_requests_employee_id_fkey(full_name, manager_id, leave_manager_id)"
            )
            .not_.is_("mc_status", "null")
            .neq("mc_status", "VALIDATED")
            .neq("status", "Rejected")
            .or_(f"mc_reminder_sent_at.is.null,mc_reminder_sent_at.lte.{recent}")
            .lte("applied_date", cutoff)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"MC reminder query failed: {e}")
        return 0

    super_admins = get_employee_ids_for_role(ADMIN)
    hr_ids = get_hr_employee_ids()
    flagged = 0

    for row in rows:
        emp = row.get("employees") or {}
        manager_id = get_leave_manager_id(emp)
        recipients = set(hr_ids) | set(super_admins)
        if manager_id:
            recipients.add(manager_id)
        recipients.discard(row["employee_id"])

        applied = datetime.fromisoformat(
            str(row["applied_date"]).replace("Z", "+00:00")
        )
        if applied.tzinfo is None:
            applied = applied.replace(tzinfo=timezone.utc)
        days_waiting = (datetime.now(timezone.utc) - applied).days

        waiting = (
            "no medical certificate has been uploaded"
            if row["mc_status"] == "AWAITING_CERTIFICATE"
            else "the uploaded certificate has not been validated by HR"
        )
        for rid in recipients:
            notify_employee(
                rid,
                title="MC Not Validated",
                message=(
                    f"{emp.get('full_name', 'An employee')}'s MC "
                    f"({row['start_date']} to {row['end_date']}) is still pending after "
                    f"{days_waiting} days: {waiting}."
                ),
                notification_type="LEAVE",
            )

        leave_repo.update(
            row["id"],
            {"mc_reminder_sent_at": datetime.now(timezone.utc).isoformat()},
        )
        flagged += 1

    return flagged


# ==========================================
# HR QUEUE: MCs THAT STILL NEED VALIDATION
# ==========================================


def get_mc_pending_validation():
    """
    Every MC (not rejected) that HR has not validated yet, oldest first,
    with how many days it has been waiting. Includes MCs still waiting
    for the certificate so HR can chase them.
    """
    try:
        rows = (
            supabase_admin.table("leave_requests")
            .select(
                "*, employees!leave_requests_employee_id_fkey(full_name, employee_id, profile_photo), "
                "leave_types(leave_name)"
            )
            .not_.is_("mc_status", "null")
            .neq("mc_status", "VALIDATED")
            .neq("status", "Rejected")
            .order("applied_date")
            .execute()
            .data
            or []
        )

        now = datetime.now(timezone.utc)
        for r in rows:
            applied = datetime.fromisoformat(
                str(r["applied_date"]).replace("Z", "+00:00")
            )
            if applied.tzinfo is None:
                applied = applied.replace(tzinfo=timezone.utc)
            r["days_waiting"] = (now - applied).days
            r["overdue"] = r["days_waiting"] >= MC_REMINDER_AFTER_DAYS

        return success_response(
            message="MCs awaiting validation fetched successfully.", data=rows
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch MCs awaiting validation.")
