"""
MC (medical leave) flow.

  Step 1  Employee applies for MC (e.g. 24-25 Oct)
                                           -> leave manager + HR + Super Admin
                                              notified, NO day count yet
                                              (see app/leaves/services.py apply_leave)
  Step 2  Employee uploads the certificate (e.g. on 26 Oct) together with the
          END DATE printed on it         -> days are calculated now
                                              (start_date .. certificate end date)
                                              and shown to HR / Super Admin ONLY.
                                              HR is notified.
  Then    HR validates the leave as MC   -> leave end date + days become final,
                                              the balance is deducted, everyone
                                              can see the days. No further action.
          HR has NOT validated 5 days after the CERTIFICATE WAS UPLOADED
          (e.g. uploaded 26 Oct -> reminder from 31 Oct, NOT counted from the
          apply date)                      -> HR, leave manager and Super Admin
                                              get a reminder (daily scheduler job)

leave_requests.mc_status: AWAITING_CERTIFICATE -> CERTIFICATE_UPLOADED -> VALIDATED
leave_requests.mc_end_date: the end date on the certificate (set at step 2)
"""

from datetime import date, datetime, timedelta, timezone
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
from app.leaves.policy_services import deduct_entitlement, release_entitlement
from app.leaves.services import (
    HR_ROLE_NAMES,
    get_hr_employee_ids,
    get_leave_manager_id,
    mask_mc_days,
)
from app.leaves.working_days import calculate_leave_days
from app.notifications.services import notify_employee

leave_repo = SupabaseRepository("leave_requests")
employee_repo = SupabaseRepository("employees")
leave_type_repo = SupabaseRepository("leave_types")

MC_REMINDER_AFTER_DAYS = 5


def _to_date(value) -> date:
    return date.fromisoformat(str(value)[:10])


def _mc_days(employee: dict, leave: dict, end: date) -> float:
    """Working days from the leave's start date to `end` (Sundays, public
    holidays and the employee's non-working Saturdays are skipped)."""
    start = _to_date(leave["start_date"])
    return calculate_leave_days(
        employee,
        start,
        end,
        half_day=bool(leave.get("is_half_day")) and end == start,
    )["total_days"]


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
    end_date: Optional[date] = None,
    request: Optional[Request] = None,
):
    """
    `end_date` is the last day of medical leave printed on the certificate.
    Defaults to the end date the employee applied with. The day count is
    calculated here, from the leave start date to that end date.
    """
    try:
        leave = _get_mc_leave_or_error(leave_id)
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id or employee_id != leave["employee_id"]:
            forbidden("You can only attach a certificate to your own MC.")

        if leave.get("mc_status") == "VALIDATED":
            bad_request("HR has already validated this MC.")
        if leave.get("status") == "Rejected":
            bad_request("This MC request was rejected.")

        start = _to_date(leave["start_date"])
        cert_end = end_date or _to_date(leave["end_date"])
        if cert_end < start:
            bad_request(
                "The certificate end date cannot be before the leave start date."
            )

        employee_row = employee_repo.get_by_id_or_404(
            employee_id, "Employee not found."
        )
        # The day count is worked out NOW, from the certificate end date.
        days = _mc_days(employee_row, leave, cert_end)

        content, ext, content_type = _validate_and_read_file(file)
        storage_path = _upload_to_storage(employee_id, content, ext, content_type)

        updated = leave_repo.update(
            leave_id,
            {
                "mc_certificate_path": storage_path,
                "mc_certificate_name": file.filename,
                "mc_uploaded_at": datetime.now(timezone.utc).isoformat(),
                "mc_status": "CERTIFICATE_UPLOADED",
                "mc_end_date": cert_end.isoformat(),
                # Provisional until HR validates (balance is NOT touched yet);
                # hidden from the employee / leave manager by mask_mc_days().
                "total_days": days,
            },
        )

        name = employee_row.get("full_name", "An employee")
        applied_end = _to_date(leave["end_date"])
        extension = (
            f" The certificate runs {(cert_end - applied_end).days} day(s) past the "
            f"applied end date ({applied_end})."
            if cert_end > applied_end
            else ""
        )
        # HR only -- the leave manager is not told the days at this stage.
        for hr_id in get_hr_employee_ids():
            if hr_id != employee_id:
                notify_employee(
                    hr_id,
                    title="MC Certificate Uploaded",
                    message=(
                        f"{name} uploaded a medical certificate: MC "
                        f"{start} to {cert_end} = {days:g} working day(s)."
                        f"{extension} Please validate it."
                    ),
                    notification_type="LEAVE",
                )

        record_audit_log(
            module="LEAVE",
            action="MC_CERTIFICATE_UPLOADED",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=leave_id,
            description=f"Medical certificate attached (end date {cert_end}, {days:g} day(s))",
            request=request,
        )

        # The employee does not see the day count until HR validates.
        mask_mc_days([updated], show_days=False, show_end_date=True)
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

        if leave.get("status") == "Rejected":
            bad_request("This MC request was rejected.")

        hr_employee_id = get_employee_id_for_auth_user(auth_user_id)

        # Make the certificate's end date the leave's end date, count the
        # final days and take them out of the balance.
        final_end = _to_date(leave.get("mc_end_date") or leave["end_date"])
        employee_row = employee_repo.get_by_id_or_404(
            leave["employee_id"], "Employee not found."
        )
        total_days = _mc_days(employee_row, leave, final_end)

        leave_type = leave_type_repo.get_by_id(
            leave["leave_type_id"],
            select="id, leave_name, default_days, entitlement_mode, is_paid, hr_managed",
        )
        balance_deducted = False
        if leave_type:
            # MCs applied before this change had days held at apply time:
            # hand those back first so the balance is never deducted twice.
            if leave.get("balance_deducted"):
                release_entitlement(leave, leave_type)
            hold = deduct_entitlement(
                leave["employee_id"], leave_type, total_days, leave_id
            )
            balance_deducted = bool(hold["balance_deducted"])

        updated = leave_repo.update(
            leave_id,
            {
                "mc_status": "VALIDATED",
                "mc_validated_by": hr_employee_id,
                "mc_validated_at": datetime.now(timezone.utc).isoformat(),
                "end_date": final_end.isoformat(),
                "total_days": total_days,
                "balance_deducted": balance_deducted,
            },
        )

        notify_employee(
            leave["employee_id"],
            title="MC Validated",
            message=(
                f"HR has validated your MC ({leave['start_date']} to {final_end}, "
                f"{total_days:g} day(s))."
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
    For every MC whose certificate was uploaded more than 5 days ago and that
    HR has still not validated, notify HR, the leave manager and Super Admin --
    every day until HR validates it (rejected leaves are skipped).
    The 5 days are counted from the certificate UPLOAD date (mc_uploaded_at),
    not from the day the leave was applied.
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
                "id, employee_id, start_date, end_date, mc_status, mc_uploaded_at, "
                "employees!leave_requests_employee_id_fkey(full_name, manager_id, leave_manager_id)"
            )
            .eq("mc_status", "CERTIFICATE_UPLOADED")
            .neq("status", "Rejected")
            .or_(f"mc_reminder_sent_at.is.null,mc_reminder_sent_at.lte.{recent}")
            .lte("mc_uploaded_at", cutoff)
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

        uploaded = datetime.fromisoformat(
            str(row["mc_uploaded_at"]).replace("Z", "+00:00")
        )
        if uploaded.tzinfo is None:
            uploaded = uploaded.replace(tzinfo=timezone.utc)
        days_waiting = (datetime.now(timezone.utc) - uploaded).days

        waiting = "the uploaded certificate has not been validated by HR"
        for rid in recipients:
            notify_employee(
                rid,
                title="MC Not Validated",
                message=(
                    f"{emp.get('full_name', 'An employee')}'s MC "
                    f"({row['start_date']} to {row['end_date']}) is still pending after "
                    f"{days_waiting} days since the certificate was uploaded: {waiting}."
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
    Every MC (not rejected) that HR has not validated yet, oldest first.
    days_waiting counts from the certificate UPLOAD date; MCs still waiting
    for the certificate have days_waiting = None (the 5-day clock hasn't started).
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
            .order("applied_date")  # oldest application first
            .execute()
            .data
            or []
        )

        now = datetime.now(timezone.utc)
        for r in rows:
            if not r.get("mc_uploaded_at"):
                r["days_waiting"] = None
                r["overdue"] = False
                continue
            uploaded = datetime.fromisoformat(
                str(r["mc_uploaded_at"]).replace("Z", "+00:00")
            )
            if uploaded.tzinfo is None:
                uploaded = uploaded.replace(tzinfo=timezone.utc)
            r["days_waiting"] = (now - uploaded).days
            r["overdue"] = r["days_waiting"] >= MC_REMINDER_AFTER_DAYS

        mask_mc_days(rows, show_days=True)  # HR / Super Admin queue
        return success_response(
            message="MCs awaiting validation fetched successfully.", data=rows
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch MCs awaiting validation.")
