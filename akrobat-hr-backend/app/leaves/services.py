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
from app.notifications.services import notify_employee
from app.notification_preferences.services import get_preference
from app.leaves.policy_services import (
    evaluate_leave_eligibility,
    validate_leave_request_against_entitlement,
    apply_entitlement_on_approval,
)

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
        select="id, leave_name, default_days, entitlement_mode, is_paid",
    )

    if not leave_type:
        bad_request(f"Unknown leave type: {leave_type_name}")

    return leave_type


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
        total_days = (data.to_date - data.from_date).days + 1

        applicant_record = employee_repo.get_by_id_or_404(
            employee_id, "Employee not found."
        )

        # Eligibility (nationality/marital_status/gender/office-vs-field
        # exclusions from leave_eligibility_rules) — e.g. foreigners
        # can't apply for NS Leave, single employees can't apply for
        # Paternity/Maternity/Childcare, field staff can't apply for
        # Replacement Leave.
        eligible, ineligible_reason = evaluate_leave_eligibility(
            applicant_record, leave_type_id
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
                "reason": data.reason,
                "status": "Pending",
            }
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
        applicant = employee_repo.get_by_id(employee_id, select="full_name, manager_id")
        manager_id = applicant.get("manager_id") if applicant else None
        applicant_name = (
            applicant.get("full_name", "An employee") if applicant else "An employee"
        )

        notify_message = (
            f"{applicant_name} applied for "
            f"{data.leave_type} from {data.from_date} to {data.to_date} "
            f"({total_days} day{'s' if total_days != 1 else ''}). "
            "Awaiting your approval."
        )

        recipient_ids = set(get_employee_ids_for_role(ADMIN))
        if manager_id:
            recipient_ids.add(manager_id)
        # Applying for one's own leave shouldn't trigger a self-notification
        # (e.g. a SUPER ADMIN who is also an employee record).
        recipient_ids.discard(employee_id)

        for recipient_id in recipient_ids:
            notify_employee(
                recipient_id,
                title="New Leave Request",
                message=notify_message,
                notification_type="LEAVE",
            )

        return success_response(message=LEAVE_APPLIED, data=leave_data)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to apply for leave.")


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


def get_all_leaves(page: int = 1, limit: int = 20, status: Optional[str] = None):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 100), 1)
        end = start + max(min(limit, 100), 1) - 1

        filters = {"status": status} if status else None

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

        report_ids = get_all_report_ids(manager_employee_id)

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

        return success_response(
            message="Team leave requests fetched successfully.",
            data=response.data or [],
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

        target_employee_id = existing.get("employee_id")
        approver_employee_id = get_employee_id_for_auth_user(auth_user_id)

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

        if data.status == "Approved":
            try:
                leave_type_full = leave_type_repo.get_by_id(
                    existing.get("leave_type_id"),
                    select="id, leave_name, default_days, entitlement_mode, is_paid",
                )
                if leave_type_full:
                    apply_entitlement_on_approval(
                        target_employee_id,
                        leave_type_full,
                        existing.get("total_days") or 0,
                        leave_id,
                    )
            except Exception as entitlement_error:
                # Don't block the approval itself over a balance/credit
                # bookkeeping failure -- log it so HR can reconcile
                # leave_balances / leave_replacement_credits manually.
                logger.error(
                    f"Failed to apply entitlement deduction for leave "
                    f"{leave_id}: {entitlement_error}"
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

        return success_response(message=message, data=updated)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update leave request status.")
