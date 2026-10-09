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


def get_hr_employee_ids() -> list:
    ids = set()
    for role in HR_ROLE_NAMES:
        ids.update(get_employee_ids_for_role(role))
    return list(ids)


def get_leave_manager_id(employee_row: Optional[dict]) -> Optional[str]:
    """Each employee has 1 leave manager; falls back to the reporting manager."""
    if not employee_row:
        return None
    return employee_row.get("leave_manager_id") or employee_row.get("manager_id")


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

        leave_type = _resolve_leave_type(data.leave_type)
        leave_type_id = leave_type["id"]

        applicant_record = employee_repo.get_by_id_or_404(
            employee_id, "Employee not found."
        )

        # Working days only: Sundays and public holidays are skipped, and
        # Saturdays count 0 / 0.5 / 1 according to the employee's own
        # Saturday schedule (see app/leaves/working_days.py).
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

        is_mc = leave_type["leave_name"].strip().upper() == SICK_LEAVE

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
        hold = deduct_entitlement(employee_id, leave_type, total_days, leave_data["id"])
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
                f"Leave applied: {data.leave_type} "
                f"({data.from_date} to {data.to_date}, {total_days} day(s))"
            ),
            new_values=leave_data,
            request=request,
        )

        # Notify whoever can act on this request. Approve/reject is gated
        # to SUPER ADMIN only (see app/leaves/routes.py — "no other role
        # may approve/reject leave, regardless of what's granted in
        # role_permissions"), so the manager alone is not guaranteed to be
        # able to action it, and previously wasn't even notified unless
        # they *also* happened to be a SUPER ADMIN. Every SUPER ADMIN now
        # gets the notification; the manager still gets a copy too so
        # they stay in the loop even though they can't approve it.
        # Best-effort: notify_employee() swallows its own errors, so this
        # never blocks the leave request from going through.
        applicant = employee_repo.get_by_id(
            employee_id, select="full_name, manager_id, leave_manager_id"
        )
        leave_manager_id = get_leave_manager_id(applicant)
        applicant_name = (
            applicant.get("full_name", "An employee") if applicant else "An employee"
        )
        day_text = f"{total_days:g} day{'s' if total_days != 1 else ''}"
        label = "MC" if is_mc else data.leave_type

        # The employee's leave manager approves, and every Super Admin is
        # told as well (they can see and decide any request). If no leave
        # manager is assigned, Super Admin is the only recipient.
        recipients = {}
        if leave_manager_id:
            recipients[leave_manager_id] = (
                f"{applicant_name} applied for {label} from {data.from_date} to "
                f"{data.to_date} ({day_text}). Awaiting your approval."
            )
        for admin_id in get_employee_ids_for_role(ADMIN):
            recipients.setdefault(
                admin_id,
                (
                    f"{applicant_name} applied for {label} from {data.from_date} to "
                    f"{data.to_date} ({day_text}). "
                    + (
                        "Sent to their leave manager for approval."
                        if leave_manager_id
                        else "No leave manager is assigned."
                    )
                ),
            )

        # MC step 1: HR is told as well, so they can follow up on the certificate.
        if is_mc:
            for hr_id in get_hr_employee_ids():
                recipients.setdefault(
                    hr_id,
                    f"{applicant_name} applied for MC from {data.from_date} to "
                    f"{data.to_date} ({day_text}). A medical certificate will follow.",
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
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(
                message="Team leave requests fetched successfully.", data=[]
            )

        report_ids = list(get_all_report_ids(manager_employee_id) or [])

        # Also everyone this person is the assigned leave manager for,
        # even if they aren't in their reporting chain.
        managed = (
            supabase_admin.table("employees")
            .select("id")
            .eq("leave_manager_id", manager_employee_id)
            .execute()
            .data
            or []
        )
        report_ids = list({*report_ids, *[m["id"] for m in managed]})

        if not report_ids:
            return success_response(
                message="Team leave requests fetched successfully.", data=[]
            )

        response = (
            supabase_admin.table("leave_requests")
            .select(LEAVE_SELECT)
            .in_("employee_id", report_ids)
            .order("applied_date", desc=True)
            .execute()
        )

        records = response.data or []

        # can_decide = this manager is the employee's assigned leave
        # manager (the person who approves/rejects), as opposed to just
        # being somewhere up their reporting chain.
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
                r["can_decide"] = lm_by_emp.get(r["employee_id"]) == manager_employee_id

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
# (route-gated to SUPER ADMIN only — see app/leaves/routes.py. The only
#  check left here is that a SUPER ADMIN who is also an employee record
#  can't approve their own leave request.)
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

        # Who may decide: the employee's leave manager, or Super Admin.
        target_row = employee_repo.get_by_id(
            target_employee_id, select="manager_id, leave_manager_id"
        )
        is_super_admin = get_role_name_for_auth_user(auth_user_id) == ADMIN
        is_leave_manager = bool(
            approver_employee_id
            and approver_employee_id == get_leave_manager_id(target_row)
        )
        if not (is_super_admin or is_leave_manager):
            forbidden(
                "Only the employee's leave manager or Super Admin can approve or reject this leave."
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
                elif not existing.get("balance_deducted"):
                    # requests created before days were held at apply time
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
# HR / SUPER ADMIN: RECORD HOSPITALISATION / MATERNITY LEAVE
# (employees cannot apply for or see these -- leave_types.hr_managed)
# ==========================================


def record_hr_managed_leave(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        leave_type = _resolve_leave_type(data.leave_type)
        if not leave_type.get("hr_managed"):
            bad_request(
                f"{data.leave_type} is not an HR-managed leave type. "
                "Employees apply for it themselves."
            )
        if data.to_date < data.from_date:
            bad_request("to_date must be on or after from_date.")

        employee_id = str(data.employee_id)
        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")
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


# -- =====================================================================
# -- leave_entitlement_form.sql  (rename to your next sql/NNN number)
# -- Leave days as plain number inputs on the Create / Edit User form,
# -- and HR-defined (custom) leave types.
# -- Safe to re-run.
# -- =====================================================================

# -- 1. Per-employee day overrides may now be half days (0.5 step).
# alter table employee_leave_overrides
#     alter column days type numeric(5,1) using days::numeric;

# -- 2. Which leave types get a "days" input on the user form.
# --    (Keeps the modal compact: Casual / Unpaid / Emergency / Hospitalisation /
# --    Compassionate / NS are NOT shown there.)
# alter table leave_types
#     add column if not exists show_in_user_form boolean not null default false;

# update leave_types
# set show_in_user_form = true
# where leave_name in (
#     'ANNUAL LEAVE',
#     'SICK LEAVE',          -- shown to staff as "Medical Leave (MC)"
#     'REPLACEMENT LEAVE',
#     'CHILDCARE LEAVE',
#     'MATERNITY LEAVE',
#     'PATERNITY LEAVE'
# );

# -- Custom leave types created by HR (POST /leaves/types) are inserted with
# -- show_in_user_form = true, entitlement_mode = 'fixed'.
