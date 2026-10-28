import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, forbidden, internal_server_error
from app.core.messages import LEAVE_APPLIED, LEAVE_APPROVED, LEAVE_REJECTED
from app.core.audit import record_audit_log
from app.core.helpers.employee_helper import (
    get_employee_id_for_auth_user,
    get_all_report_ids,
    get_employee_ids_for_role,
)
from app.core.constants import ADMIN
from app.core.database import supabase_admin
from app.core import realtime
from app.notifications.services import notify_employee
from app.notification_preferences.services import get_preference
from app.core.permissions import get_role_name_for_auth_user
from app.leaves.working_days import calculate_leave_days
from app.leaves.policy_services import (
    SICK_LEAVE,
    evaluate_self_apply_access,
    evaluate_leave_eligibility,
    validate_leave_request_against_entitlement,
    deduct_entitlement,
    release_entitlement,
)

HR_ROLE_NAMES = ("HR ADMIN", "HR EXECUTIVE", "HR")

leave_repo = SupabaseRepository("leave_requests")
leave_type_repo = SupabaseRepository("leave_types")
employee_repo = SupabaseRepository("employees")

LEAVE_SELECT = (
    "*, employees!leave_requests_employee_id_fkey(full_name, employee_id, profile_photo), "
    "leave_types(leave_name)"
)


def _resolve_leave_type_id(leave_type_name: str) -> str:
    return _resolve_leave_type(leave_type_name)["id"]


def _resolve_leave_type(leave_type_name: str) -> dict:
    leave_type = leave_type_repo.find_one(
        {"leave_name": leave_type_name.strip().upper()},
        select="id, leave_name, default_days, entitlement_mode, is_paid, hr_managed",
    )

    if not leave_type:
        bad_request(f"Unknown leave type: {leave_type_name}")

    return leave_type


def mask_mc_days(records, show_days: bool, show_end_date: Optional[bool] = None):
    """
    MC days are NOT known when the employee applies -- they are worked out
    from the end date on the medical certificate (see mc_services.py).

      * AWAITING_CERTIFICATE     -> nobody sees a day count (none exists yet)
      * CERTIFICATE_UPLOADED     -> only HR / Super Admin see days + certificate
                                    end date (show_days=True)
      * VALIDATED                -> everybody sees the final days
    `show_end_date` (default: same as show_days) lets the employee still see the
    certificate end date they typed in themselves -- only the day count is held back.
    Mutates and returns `records` (a list of leave_requests rows).
    """
    if show_end_date is None:
        show_end_date = show_days
    for r in records or []:
        status = r.get("mc_status")
        if not status or status == "VALIDATED":
            continue
        if status == "AWAITING_CERTIFICATE" or not show_days:
            r["total_days"] = None
        if not show_end_date:
            r["mc_end_date"] = None
    return records


def get_hr_employee_ids() -> list:
    ids = set()
    for role in HR_ROLE_NAMES:
        ids.update(get_employee_ids_for_role(role))
    return list(ids)


# Employees with NO reporting manager have their leave routed to this Super
# Admin instead. Matched by name (case-insensitive, substring) against the
# Super Admins only, so a same-named non-admin can never become the approver.
# Override per environment with DEFAULT_LEAVE_APPROVER_NAME.
DEFAULT_LEAVE_APPROVER_NAME = os.getenv("DEFAULT_LEAVE_APPROVER_NAME", "Muriel")


def get_default_approver_id() -> Optional[str]:
    """employees.id of the Super Admin who approves leave for employees that
    have no reporting manager (see DEFAULT_LEAVE_APPROVER_NAME). None if no
    Super Admin matches, in which case such requests have no approver."""
    try:
        admin_ids = list(get_employee_ids_for_role(ADMIN) or [])
        if not admin_ids:
            return None
        rows = (
            supabase_admin.table("employees")
            .select("id, full_name")
            .in_("id", admin_ids)
            .execute()
            .data
            or []
        )
        needle = DEFAULT_LEAVE_APPROVER_NAME.strip().lower()
        for row in rows:
            if needle and needle in (row.get("full_name") or "").lower():
                return row["id"]
        logger.error(
            f"No Super Admin matches DEFAULT_LEAVE_APPROVER_NAME "
            f"'{DEFAULT_LEAVE_APPROVER_NAME}'; leave for employees without a "
            f"reporting manager has no approver."
        )
    except Exception as e:
        logger.error(f"Failed to resolve default leave approver: {e}")
    return None


def get_leave_manager_id(employee_row: Optional[dict]) -> Optional[str]:
    """Who approves this employee's leave: their REPORTING MANAGER
    (employees.manager_id), whatever that manager's role is; else the old
    employees.leave_manager_id; else -- when the employee has no reporting
    manager at all -- the default approver (Super Admin Muriel, see
    get_default_approver_id). Every other Super Admin / HR only views."""
    if not employee_row:
        return None
    return (
        employee_row.get("manager_id")
        or employee_row.get("leave_manager_id")
        or get_default_approver_id()
    )


# ==========================================
# APPLY LEAVE (self-service — any authenticated employee)
# ==========================================


def apply_leave(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        if data.to_date < data.from_date:
            bad_request("to_date must be on or after from_date.")

        # Part-time staff have no leave entitlement.
        _pt = (
            supabase_admin.table("employees")
            .select("is_part_time")
            .eq("id", employee_id)
            .maybe_single()
            .execute()
        )
        if _pt and _pt.data and _pt.data.get("is_part_time"):
            forbidden("Part-time employees are not eligible for leave.")

        leave_type = _resolve_leave_type(data.leave_type)
        leave_type_id = leave_type["id"]
        is_mc = leave_type["leave_name"].strip().upper() == SICK_LEAVE

        applicant_record = employee_repo.get_by_id_or_404(
            employee_id, "Employee not found."
        )

        # Working days only: Sundays and public holidays are skipped, and
        # Saturdays count 0 / 0.5 / 1 according to the employee's own
        # Saturday schedule (see app/leaves/working_days.py).
        #
        # MC is the exception: the real end date is only known from the
        # medical certificate, which the employee uploads AFTER the leave.
        # So no days are counted (or held) now -- they are calculated when
        # the certificate end date is submitted, and the balance is taken
        # when HR validates (see app/leaves/mc_services.py).
        if is_mc:
            total_days = 0
        else:
            total_days = calculate_leave_days(
                applicant_record,
                data.from_date,
                data.to_date,
                half_day=bool(getattr(data, "half_day", False)),
            )["total_days"]

        # Eligibility (nationality/marital_status/gender/office-vs-field
        # exclusions from leave_eligibility_rules) — e.g. foreigners
        # can't apply for NS Leave, single employees can't apply for
        # Paternity/Maternity/Childcare, field staff can't apply for
        # Replacement Leave.
        eligible, ineligible_reason = evaluate_self_apply_access(
            applicant_record, leave_type
        )
        if not eligible:
            bad_request(ineligible_reason or f"Not eligible for {data.leave_type}.")

        # Entitlement check. NS Leave and Replacement Leave are
        # event-based (checked against leave_replacement_credits /
        # skipped entirely for NS) rather than a leave_balances row;
        # Unpaid Leave is never balance-checked (payroll deducts via
        # working_days_per_week instead); fixed/tiered types must have
        # enough remaining_days for the current year.
        validate_leave_request_against_entitlement(
            applicant_record, leave_type, total_days
        )

        leave_data = leave_repo.create(
            {
                "employee_id": employee_id,
                "leave_type_id": leave_type_id,
                "start_date": data.from_date.isoformat(),
                "end_date": data.to_date.isoformat(),
                "total_days": total_days,
                "is_half_day": bool(getattr(data, "half_day", False)),
                "reason": data.reason,
                "status": "Pending",
                # MC step 1 done; step 2 (certificate upload) still to come.
                "mc_status": "AWAITING_CERTIFICATE" if is_mc else None,
            }
        )

        # Balance updates as soon as the employee applies: the days are
        # held now, confirmed on approval, handed back on rejection.
        # (MC holds nothing now -- its days don't exist yet.)
        if not is_mc:
            hold = deduct_entitlement(
                employee_id, leave_type, total_days, leave_data["id"]
            )
            if hold["balance_deducted"]:
                leave_data = leave_repo.update(
                    leave_data["id"],
                    {
                        "balance_deducted": True,
                        "replacement_allocation": hold["replacement_allocation"],
                    },
                )

        record_audit_log(
            module="LEAVE",
            action="APPLY",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=leave_data.get("id"),
            description=(
                f"MC applied ({data.from_date} to {data.to_date}); "
                "days will be calculated from the certificate end date"
                if is_mc
                else f"Leave applied: {data.leave_type} "
                f"({data.from_date} to {data.to_date}, {total_days} day(s))"
            ),
            new_values=leave_data,
            request=request,
        )

        # Notify whoever can act on this request (see below).
        # Best-effort: notify_employee() swallows its own errors, so this
        # never blocks the leave request from going through.
        applicant = employee_repo.get_by_id(
            employee_id, select="full_name, manager_id, leave_manager_id"
        )
        leave_manager_id = get_leave_manager_id(applicant)
        applicant_name = (
            applicant.get("full_name", "An employee") if applicant else "An employee"
        )
        # No day count in MC notifications: the days are only known (and shown
        # to HR first) once the certificate end date is submitted.
        day_text = (
            "" if is_mc else f" ({total_days:g} day{'s' if total_days != 1 else ''})"
        )
        label = "MC" if is_mc else data.leave_type

        # The employee's approver (reporting manager, or Super Admin Muriel
        # when they have none) is asked to approve; every other Super Admin
        # is told as well, but only so they can SEE the request.
        recipients = {}
        if leave_manager_id:
            recipients[leave_manager_id] = (
                f"{applicant_name} applied for {label} from {data.from_date} to "
                f"{data.to_date}{day_text}. Awaiting your approval."
            )
        for admin_id in get_employee_ids_for_role(ADMIN):
            recipients.setdefault(
                admin_id,
                (
                    f"{applicant_name} applied for {label} from {data.from_date} to "
                    f"{data.to_date}{day_text}. "
                    + (
                        "Sent to their approver for approval."
                        if leave_manager_id
                        else "No approver is assigned for this employee."
                    )
                ),
            )

        # MC step 1: HR is told as well, so they can follow up on the certificate.
        if is_mc:
            for hr_id in get_hr_employee_ids():
                recipients.setdefault(
                    hr_id,
                    f"{applicant_name} applied for MC from {data.from_date} to "
                    f"{data.to_date}. The medical certificate will follow; the "
                    "number of days is calculated from its end date.",
                )

        recipients.pop(employee_id, None)
        for recipient_id, message_text in recipients.items():
            notify_employee(
                recipient_id,
                title="New MC Application" if is_mc else "New Leave Request",
                message=message_text,
                notification_type="LEAVE",
            )

        # Push to any open dashboard scoped to see this employee (see
        # app/core/realtime.py) — the manager's Pending Requests widget
        # and HR/Super Admin's leave queue update immediately instead of
        # waiting for a manual refresh.
        realtime.broadcast_threadsafe(
            {
                "type": "leave_event",
                "action": "applied",
                "employee_id": employee_id,
            }
        )

        mask_mc_days([leave_data], show_days=False, show_end_date=True)
        return success_response(message=LEAVE_APPLIED, data=leave_data)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to apply for leave.")


# ==========================================
# PREVIEW LEAVE DAYS (self-service) — the same count apply_leave() will
# store, so the Apply Leave screen shows exactly what will be deducted.
# ==========================================


def preview_leave_days(auth_user_id: str, from_date, to_date, half_day: bool = False):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            forbidden("No employee profile is linked to this account.")
        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")
        result = calculate_leave_days(employee, from_date, to_date, half_day)
        return success_response(message="Leave days calculated.", data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to calculate leave days.")


# ==========================================
# GET MY LEAVES (self-service — own records only)
# ==========================================


def get_my_leaves(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(
                message="Leave requests fetched successfully.", data=[]
            )

        records, _total = leave_repo.list(
            select=LEAVE_SELECT,
            filters={"employee_id": employee_id},
            order_by="applied_date",
            ascending=False,
        )

        # Own MC: no days until HR has validated it.
        mask_mc_days(records, show_days=False, show_end_date=True)
        return success_response(
            message="Leave requests fetched successfully.", data=records
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave requests.")


# ==========================================
# GET LEAVE TYPES (HR / Admin — org-wide config, requires VIEW_LEAVE_REQUESTS)
# Exposes each leave type's default_days, i.e. the annual allocation.
# Used by the Leave Balance screen to compute remaining = allocation - used.
# ==========================================


def get_leave_types():
    try:
        records, _total = leave_type_repo.list(
            select="id, leave_name, default_days",
            order_by="leave_name",
        )
        return success_response(
            message="Leave types fetched successfully.", data=records
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave types.")


# ==========================================
# GET ALL LEAVES (HR / Admin — company-wide, requires VIEW_LEAVE_REQUESTS)
# ==========================================


def get_all_leaves(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    employee_id: Optional[str] = None,
):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 100), 1)
        end = start + max(min(limit, 100), 1) - 1

        filters = {}
        if status:
            filters["status"] = status
        if employee_id:
            filters["employee_id"] = employee_id
        filters = filters or None

        records, total = leave_repo.list(
            select=LEAVE_SELECT,
            filters=filters,
            order_by="applied_date",
            ascending=False,
            start=start,
            end=end,
        )

        mask_mc_days(records, show_days=True)  # HR / Super Admin see MC days first
        return success_response(
            message="Leave requests fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave requests.")


# ==========================================
# GET TEAM LEAVES (Manager — direct + indirect reports only)
# ==========================================


def get_team_leaves(auth_user_id: str):
    """Leave Requests page data.

    VISIBILITY
      - HR / Super Admin: every employee's leave request (company-wide).
      - Everyone else (Manager, or any employee who is somebody's reporting
        manager): their direct + indirect reports, plus anyone they are the
        assigned leave manager for.

    PERMISSION (independent of visibility)
      Each record carries can_decide = True ONLY when the caller is that
      employee's reporting manager (see get_leave_manager_id). Manager /
      HR / Super Admin who are not that employee's reporting manager get
      can_decide = False, i.e. view-only. update_leave_status enforces the
      same rule server-side.
    """
    try:
        me = get_employee_id_for_auth_user(auth_user_id)
        role_name = (get_role_name_for_auth_user(auth_user_id) or "").upper()
        company_wide = role_name == ADMIN or role_name in HR_ROLE_NAMES

        query = (
            supabase_admin.table("leave_requests")
            .select(LEAVE_SELECT)
            .order("applied_date", desc=True)
        )

        if not company_wide:
            if not me:
                return success_response(
                    message="Team leave requests fetched successfully.", data=[]
                )

            report_ids = list(get_all_report_ids(me) or [])

            # Also everyone this person is the assigned leave manager for,
            # even if they aren't in their reporting chain.
            managed = (
                supabase_admin.table("employees")
                .select("id")
                .eq("leave_manager_id", me)
                .execute()
                .data
                or []
            )
            report_ids = list({*report_ids, *[m["id"] for m in managed]})

            if not report_ids:
                return success_response(
                    message="Team leave requests fetched successfully.", data=[]
                )

            query = query.in_("employee_id", report_ids)

        records = query.execute().data or []

        # HR / Super Admin see the MC days as soon as the certificate end date
        # is in; a leave manager only sees them after HR validates.
        mask_mc_days(records, show_days=company_wide)

        if records:
            lm_rows = (
                supabase_admin.table("employees")
                .select("id, manager_id, leave_manager_id")
                .in_("id", list({r["employee_id"] for r in records}))
                .execute()
                .data
                or []
            )
            lm_by_emp = {e["id"]: get_leave_manager_id(e) for e in lm_rows}
            for r in records:
                r["can_decide"] = bool(
                    me
                    and lm_by_emp.get(r["employee_id"]) == me
                    and r["employee_id"] != me
                )

        return success_response(
            message="Team leave requests fetched successfully.",
            data=records,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch team leave requests.")


# ==========================================
# APPROVE / REJECT LEAVE
# Only the employee's REPORTING MANAGER may decide (any role -- being
# someone's reporting manager is what counts, not the role name). Manager /
# HR / Super Admin can view requests but cannot approve/reject unless they
# are that employee's reporting manager. Nobody can decide their own request.
# ==========================================


def update_leave_status(
    leave_id: str,
    data,
    auth_user_id: str,
    request: Optional[Request] = None,
):
    try:
        existing = leave_repo.get_by_id_or_404(leave_id, "Leave request not found.")

        if existing.get("status") != "Pending":
            bad_request(
                f"This leave request has already been {str(existing.get('status')).lower()}."
            )

        if data.status not in ("Approved", "Rejected"):
            bad_request("Status must be Approved or Rejected.")

        target_employee_id = existing.get("employee_id")
        approver_employee_id = get_employee_id_for_auth_user(auth_user_id)

        # Who may decide: the employee's reporting manager ONLY, whatever
        # their role. Manager / HR / Super Admin who are not that employee's
        # reporting manager can view the request but cannot approve/reject.
        target_row = employee_repo.get_by_id(
            target_employee_id, select="manager_id, leave_manager_id"
        )
        assigned_approver_id = get_leave_manager_id(target_row)
        is_reporting_manager = bool(
            approver_employee_id and approver_employee_id == assigned_approver_id
        )
        if not is_reporting_manager:
            forbidden(
                "Only the employee's reporting manager can approve or reject this leave."
            )

        if approver_employee_id and approver_employee_id == target_employee_id:
            forbidden("You cannot approve or reject your own leave request.")

        updated = leave_repo.update(
            leave_id,
            {
                "status": data.status,
                "approved_by": approver_employee_id,
                "approved_date": datetime.now(timezone.utc).isoformat(),
            },
        )

        try:
            supabase_admin.table("leave_approval_history").insert(
                {
                    "leave_request_id": leave_id,
                    "action": data.status.upper(),
                    "action_by": approver_employee_id,
                    "comments": data.comments,
                }
            ).execute()
        except Exception as history_error:
            # Approval history is a secondary audit trail; don't fail the
            # approval itself if this insert has an issue.
            logger.error(f"Failed to write leave_approval_history: {history_error}")

        try:
            leave_type_full = leave_type_repo.get_by_id(
                existing.get("leave_type_id"),
                select="id, leave_name, default_days, entitlement_mode, is_paid, hr_managed",
            )
            if leave_type_full:
                if data.status == "Rejected":
                    # give the held days back
                    release_entitlement(existing, leave_type_full)
                    leave_repo.update(leave_id, {"balance_deducted": False})
                elif not existing.get("balance_deducted") and not existing.get(
                    "mc_status"
                ):
                    # requests created before days were held at apply time
                    # (never for MC: its days are taken when HR validates it)
                    deduct_entitlement(
                        target_employee_id,
                        leave_type_full,
                        existing.get("total_days") or 0,
                        leave_id,
                    )
        except Exception as entitlement_error:
            # Don't block the decision itself over balance bookkeeping --
            # log it so HR can reconcile leave_balances manually.
            logger.error(
                f"Failed to update entitlement for leave {leave_id}: {entitlement_error}"
            )

        record_audit_log(
            module="LEAVE",
            action=data.status.upper(),
            performed_by=auth_user_id,
            target_employee_id=target_employee_id,
            record_id=leave_id,
            description=(
                f"Leave request {data.status.lower()}"
                + (f" — {data.comments}" if data.comments else "")
            ),
            old_values=existing,
            new_values=updated,
            request=request,
        )

        # Notify the employee whose leave was decided on. Best-effort:
        # notify_employee() swallows its own errors, so a broken
        # notifications insert never blocks the approval/rejection itself.
        leave_type_row = leave_type_repo.get_by_id(
            existing.get("leave_type_id"), select="leave_name"
        )
        leave_type_name = (
            leave_type_row.get("leave_name") if leave_type_row else "Leave"
        )
        # Gated by the employee's own "Leave request updates" toggle
        # (Settings > Notifications) -- this is the exact "your leave was
        # approved/rejected/commented on" case that toggle describes.
        # Defaults to on for anyone who hasn't saved preferences yet.
        if get_preference(target_employee_id, "leave_updates"):
            notify_employee(
                target_employee_id,
                title=f"Leave {data.status}",
                message=(
                    f"Your {leave_type_name.title()} request "
                    f"({existing.get('start_date')} to {existing.get('end_date')}) "
                    f"has been {data.status.lower()}"
                    + (f" — {data.comments}" if data.comments else ".")
                ),
                notification_type="LEAVE",
            )

        message = LEAVE_APPROVED if data.status == "Approved" else LEAVE_REJECTED

        # Same live-push as apply_leave() above, so the employee's own
        # "My Leave Requests" and their manager's dashboard both flip to
        # the new status immediately instead of on next refresh.
        realtime.broadcast_threadsafe(
            {
                "type": "leave_event",
                "action": data.status.lower(),
                "employee_id": target_employee_id,
            }
        )

        return success_response(message=message, data=updated)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update leave request status.")


# ==========================================
# HR / SUPER ADMIN: RECORD HOSPITALISATION LEAVE (Maternity / Paternity: Super Admin only)
# (employees cannot apply for or see these -- leave_types.hr_managed)
# ==========================================


def record_hr_managed_leave(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        leave_type = _resolve_leave_type(data.leave_type)
        leave_name = (leave_type.get("leave_name") or "").strip().upper()
        super_admin_only = leave_name in ("MATERNITY LEAVE", "PATERNITY LEAVE")
        if not leave_type.get("hr_managed") and not super_admin_only:
            bad_request(
                f"{data.leave_type} is not an HR-managed leave type. "
                "Employees apply for it themselves."
            )
        # Maternity / Paternity can be recorded by Super Admin only.
        if super_admin_only and (
            (get_role_name_for_auth_user(auth_user_id) or "").strip().upper() != ADMIN
        ):
            forbidden(f"{leave_name.title()} can be recorded by Super Admin only.")
        if data.to_date < data.from_date:
            bad_request("to_date must be on or after from_date.")

        employee_id = str(data.employee_id)
        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")
        if super_admin_only:
            eligible, reason = evaluate_leave_eligibility(employee, leave_type["id"])
            if not eligible:
                bad_request(
                    reason
                    or f"{leave_name.title()} is not applicable for this employee."
                )
        total_days = calculate_leave_days(employee, data.from_date, data.to_date)[
            "total_days"
        ]

        validate_leave_request_against_entitlement(employee, leave_type, total_days)

        approver_id = get_employee_id_for_auth_user(auth_user_id)
        leave_data = leave_repo.create(
            {
                "employee_id": employee_id,
                "leave_type_id": leave_type["id"],
                "start_date": data.from_date.isoformat(),
                "end_date": data.to_date.isoformat(),
                "total_days": total_days,
                "reason": data.reason,
                "status": "Approved",
                "approved_by": approver_id,
                "approved_date": datetime.now(timezone.utc).isoformat(),
            }
        )
        hold = deduct_entitlement(employee_id, leave_type, total_days, leave_data["id"])
        if hold["balance_deducted"]:
            leave_data = leave_repo.update(leave_data["id"], {"balance_deducted": True})

        record_audit_log(
            module="LEAVE",
            action="HR_RECORDED_LEAVE",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=leave_data.get("id"),
            description=(
                f"{data.leave_type.title()} recorded by HR "
                f"({data.from_date} to {data.to_date}, {total_days} day(s))"
            ),
            new_values=leave_data,
            request=request,
        )
        return success_response(message="Leave recorded.", data=leave_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to record leave.")
