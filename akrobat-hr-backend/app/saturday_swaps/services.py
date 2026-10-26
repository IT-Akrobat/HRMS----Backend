"""
Saturday Swap.

An employee on a Saturday pattern (e.g. "2nd & 4th Saturday") asks to
  * take OFF one of their regular working Saturdays   (off_date), and
  * WORK one of their regular off Saturdays instead    (work_date).

Flow: employee applies -> the employee's reporting manager approves/rejects
(same approver rule as leave: get_leave_manager_id) -> once Approved,
app/attendance/services.py::_get_employee_shift() treats work_date as a
working day and off_date as a week-off. That single hook is what makes the
worked Saturday record as Present (no Absent / LOP on the swapped-off one).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.core import realtime
from app.core.audit import record_audit_log
from app.core.database import supabase_admin
from app.core.exceptions import bad_request, forbidden, internal_server_error, not_found
from app.core.helpers.employee_helper import get_employee_id_for_auth_user
from app.core.logger import logger
from app.core.responses import success_response
from app.notifications.services import notify_employee
from app.notification_preferences.services import get_preference

# Both Saturdays must fall in the same calendar month. Flip to False if the
# company wants swaps across months.
REQUIRE_SAME_MONTH = True

# The Apply screen offers the current month only. Once the month is within
# this many days of ending (inclusive of today), next month is offered too.
NEXT_MONTH_OPENS_DAYS_BEFORE_END = 7

LIVE_STATUSES = ("Pending", "Approved")

SWAP_SELECT = (
    "*, employees!saturday_swaps_employee_id_fkey"
    "(full_name, employee_id, profile_photo, manager_id, leave_manager_id)"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _broadcast(action: str, employee_id: str):
    # Same event the leave screens already listen to, so open Saturday Swap /
    # dashboard pages refresh immediately.
    try:
        realtime.broadcast_threadsafe(
            {"type": "leave_event", "action": action, "employee_id": employee_id}
        )
    except Exception as e:
        logger.warning(f"Saturday swap broadcast failed: {e}")


def _today() -> date:
    from app.attendance.services import _today_in_company_tz

    return _today_in_company_tz()


def _regular_shift(employee_id: str, day: date):
    """Shift on `day` IGNORING any swaps -> the employee's normal pattern."""
    from app.attendance.services import _get_employee_shift

    return _get_employee_shift(employee_id, day, ignore_swaps=True)


def _month_end(day: date) -> date:
    nxt = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _nth_saturday(day: date) -> int:
    return (day.day - 1) // 7 + 1


def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}.get(n, f"{n}th")


def _label(day: date) -> str:
    return f"{_ordinal(_nth_saturday(day))} Saturday, {day.strftime('%d %b %Y')}"


def _employee_row(employee_id: str) -> dict:
    row = (
        supabase_admin.table("employees")
        .select(
            "id, full_name, employee_id, work_location, nationality, "
            "manager_id, leave_manager_id"
        )
        .eq("id", employee_id)
        .maybe_single()
        .execute()
    )
    return (row.data if row else None) or {}


def _approver_id(employee_row: dict) -> Optional[str]:
    from app.leaves.services import get_leave_manager_id

    return get_leave_manager_id(employee_row)


def _holiday_dates(employee_row: dict, start: date, end: date) -> set:
    try:
        from app.leaves.working_days import (
            _holiday_dates as load,
            detect_holiday_country,
        )

        return load(detect_holiday_country(employee_row), start, end)
    except Exception as e:
        logger.error(f"Saturday swap: unable to load holidays: {e}")
        return set()


def _live_swap_conflicts(
    employee_id: str, dates: list, exclude_id: Optional[str] = None
) -> list:
    keys = ",".join(d.isoformat() for d in dates)
    rows = (
        supabase_admin.table("saturday_swaps")
        .select("id, work_date, off_date, status")
        .eq("employee_id", employee_id)
        .in_("status", list(LIVE_STATUSES))
        .or_(f"work_date.in.({keys}),off_date.in.({keys})")
        .execute()
        .data
        or []
    )
    return [r for r in rows if r["id"] != exclude_id]


def _validate_swap(
    employee_id: str,
    employee_row: dict,
    work_date: date,
    off_date: date,
    exclude_id: Optional[str] = None,
    check_past: bool = True,
):
    if work_date.weekday() != 5 or off_date.weekday() != 5:
        bad_request("Both dates must be Saturdays.")
    if work_date == off_date:
        bad_request("The working Saturday and the off Saturday must be different.")

    if check_past:
        today = _today()
        if work_date < today or off_date < today:
            bad_request("Saturday swaps can only be requested for today or later.")

    if REQUIRE_SAME_MONTH and (
        work_date.year != off_date.year or work_date.month != off_date.month
    ):
        bad_request("Both Saturdays must be in the same month.")

    if not _regular_shift(employee_id, off_date):
        bad_request(
            f"{_label(off_date)} is not one of your regular working Saturdays, "
            "so there is nothing to take off."
        )
    if _regular_shift(employee_id, work_date):
        bad_request(
            f"{_label(work_date)} is already a regular working Saturday for you."
        )

    holidays = _holiday_dates(
        employee_row, min(work_date, off_date), max(work_date, off_date)
    )
    for d in (work_date, off_date):
        if d in holidays:
            bad_request(f"{_label(d)} is a public holiday and can't be swapped.")

    if _live_swap_conflicts(employee_id, [work_date, off_date], exclude_id):
        bad_request(
            "You already have a pending or approved Saturday swap using one of these dates."
        )

    leaves = (
        supabase_admin.table("leave_requests")
        .select("id, start_date, end_date")
        .eq("employee_id", employee_id)
        .in_("status", list(LIVE_STATUSES))
        .lte("start_date", max(work_date, off_date).isoformat())
        .gte("end_date", min(work_date, off_date).isoformat())
        .execute()
        .data
        or []
    )
    for d in (work_date, off_date):
        for lv in leaves:
            if str(lv["start_date"])[:10] <= d.isoformat() <= str(lv["end_date"])[:10]:
                bad_request(
                    f"You have a leave request covering {_label(d)}. "
                    "Cancel it first or pick another Saturday."
                )

    already = (
        supabase_admin.table("attendance")
        .select("id")
        .eq("employee_id", employee_id)
        .eq("attendance_date", off_date.isoformat())
        .limit(1)
        .execute()
        .data
    )
    if already:
        bad_request(f"You already have an attendance record on {_label(off_date)}.")


def _decorate(row: dict, viewer_employee_id: Optional[str]) -> dict:
    emp = row.get("employees") or {}
    approver = _approver_id(
        {
            "manager_id": emp.get("manager_id"),
            "leave_manager_id": emp.get("leave_manager_id"),
        }
    )
    row["can_decide"] = bool(
        row.get("status") == "Pending"
        and viewer_employee_id
        and viewer_employee_id == approver
        and viewer_employee_id != row.get("employee_id")
    )
    return row


# ---------------------------------------------------------------------------
# employee: eligible Saturdays for the Apply form
# ---------------------------------------------------------------------------


def get_swap_options(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            bad_request("Employee profile not found.")
        emp = _employee_row(employee_id)

        today = _today()
        month_end = _month_end(today)
        next_month_open = (month_end - today).days < NEXT_MONTH_OPENS_DAYS_BEFORE_END
        end = (
            _month_end(month_end + timedelta(days=1)) if next_month_open else month_end
        )
        window_days = (end - today).days
        months = [today.strftime("%Y-%m")]
        if next_month_open:
            months.append((month_end + timedelta(days=1)).strftime("%Y-%m"))
        next_opens_on = (
            None
            if next_month_open
            else (
                month_end - timedelta(days=NEXT_MONTH_OPENS_DAYS_BEFORE_END - 1)
            ).isoformat()
        )
        holidays = _holiday_dates(emp, today, end)

        busy = set()
        for r in _live_swap_conflicts(
            employee_id,
            [today + timedelta(days=i) for i in range(0, window_days + 1)],
        ):
            busy.add(str(r["work_date"])[:10])
            busy.add(str(r["off_date"])[:10])

        working, off = [], []
        day = today + timedelta(days=(5 - today.weekday()) % 7)
        while day <= end:
            if day not in holidays and day.isoformat() not in busy:
                item = {
                    "date": day.isoformat(),
                    "nth": _nth_saturday(day),
                    "label": _label(day),
                    "month": day.strftime("%Y-%m"),
                }
                (working if _regular_shift(employee_id, day) else off).append(item)
            day += timedelta(days=7)

        hint = None
        if not working and not off:
            hint = "No Saturdays are available in the next few weeks (holidays or existing swaps)."
        elif not working:
            hint = (
                "Your profile has no regular working Saturdays, so there is nothing to "
                "swap out. Ask HR to check your Saturday setting (Works Saturday / "
                "Alternate Saturday)."
            )
        elif not off:
            hint = (
                "Every Saturday is a working day for you, so there is no off Saturday "
                "to swap in. Ask HR to set your Saturday pattern to 'Alternate Saturday "
                "(2nd & 4th)'."
            )

        return success_response(
            message="Saturday swap options fetched successfully.",
            data={
                "working_saturdays": working,  # candidates for off_date
                "off_saturdays": off,  # candidates for work_date
                "same_month_required": REQUIRE_SAME_MONTH,
                "months": months,  # months the screen should show, in order
                "next_month_opens_on": next_opens_on,  # None once next month is open
                "hint": hint,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to load Saturday swap options.")


# ---------------------------------------------------------------------------
# apply / list
# ---------------------------------------------------------------------------


def apply_saturday_swap(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            bad_request("Employee profile not found.")
        emp = _employee_row(employee_id)

        _validate_swap(employee_id, emp, data.work_date, data.off_date)

        created = (
            supabase_admin.table("saturday_swaps")
            .insert(
                {
                    "employee_id": employee_id,
                    "work_date": data.work_date.isoformat(),
                    "off_date": data.off_date.isoformat(),
                    "reason": data.reason.strip(),
                    "status": "Pending",
                }
            )
            .execute()
            .data
        )
        swap = created[0]

        approver_id = _approver_id(emp)
        name = emp.get("full_name") or "An employee"
        text = (
            f"{name} wants to work {_label(data.work_date)} instead of "
            f"{_label(data.off_date)}."
        )
        if approver_id and approver_id != employee_id:
            notify_employee(
                approver_id,
                title="New Saturday Swap Request",
                message=text,
                notification_type="LEAVE",
            )
        else:
            from app.leaves.services import get_hr_employee_ids

            for hr_id in get_hr_employee_ids():
                if hr_id != employee_id:
                    notify_employee(
                        hr_id,
                        title="New Saturday Swap Request",
                        message=text + " No approver is assigned for this employee.",
                        notification_type="LEAVE",
                    )

        record_audit_log(
            module="SATURDAY_SWAP",
            action="CREATE",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=swap["id"],
            description=text,
            new_values=swap,
            request=request,
        )
        _broadcast("applied", employee_id)
        return success_response(
            message="Saturday swap requested. It will apply once your manager approves.",
            data=swap,
            status_code=201,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to request the Saturday swap.")


def get_my_swaps(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(message="Saturday swaps fetched.", data=[])
        rows = (
            supabase_admin.table("saturday_swaps")
            .select(SWAP_SELECT)
            .eq("employee_id", employee_id)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        return success_response(
            message="Saturday swaps fetched.",
            data=[_decorate(r, employee_id) for r in rows],
        )
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch Saturday swaps.")


def get_swaps_to_decide(auth_user_id: str):
    """Requests where the caller is the employee's approver (any status)."""
    try:
        me = get_employee_id_for_auth_user(auth_user_id)
        if not me:
            return success_response(message="Saturday swaps fetched.", data=[])
        rows = (
            supabase_admin.table("saturday_swaps")
            .select(SWAP_SELECT)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
            .data
            or []
        )
        mine = []
        for r in rows:
            emp = r.get("employees") or {}
            approver = _approver_id(
                {
                    "manager_id": emp.get("manager_id"),
                    "leave_manager_id": emp.get("leave_manager_id"),
                }
            )
            if approver == me and r.get("employee_id") != me:
                mine.append(_decorate(r, me))
        return success_response(message="Saturday swaps fetched.", data=mine)
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch Saturday swaps.")


def get_all_swaps(
    auth_user_id: str, status: Optional[str] = None, page: int = 1, limit: int = 50
):
    """HR / Super Admin company-wide view (view-only unless they are the approver)."""
    try:
        me = get_employee_id_for_auth_user(auth_user_id)
        query = supabase_admin.table("saturday_swaps").select(SWAP_SELECT)
        if status:
            query = query.eq("status", status)
        start = (page - 1) * limit
        rows = (
            query.order("created_at", desc=True)
            .range(start, start + limit - 1)
            .execute()
            .data
            or []
        )
        return success_response(
            message="Saturday swaps fetched.",
            data=[_decorate(r, me) for r in rows],
        )
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch Saturday swaps.")


# ---------------------------------------------------------------------------
# approve / reject / cancel
# ---------------------------------------------------------------------------


def update_swap_status(
    swap_id: str, data, auth_user_id: str, request: Optional[Request] = None
):
    try:
        existing = _get_swap_or_404(swap_id)
        if existing.get("status") != "Pending":
            bad_request(
                f"This request has already been {str(existing.get('status')).lower()}."
            )
        if data.status not in ("Approved", "Rejected"):
            bad_request("Status must be Approved or Rejected.")

        approver_employee_id = get_employee_id_for_auth_user(auth_user_id)
        target_id = existing["employee_id"]
        target = _employee_row(target_id)

        if not approver_employee_id or approver_employee_id != _approver_id(target):
            forbidden(
                "Only the employee's reporting manager can approve or reject this request."
            )
        if approver_employee_id == target_id:
            forbidden("You cannot approve or reject your own request.")

        work_date = date.fromisoformat(str(existing["work_date"])[:10])
        off_date = date.fromisoformat(str(existing["off_date"])[:10])

        if data.status == "Approved":
            # Re-check: the employee's situation may have changed since they
            # applied (a leave got approved, etc.). Past dates are allowed here --
            # a manager may approve a swap on/after the day.
            _validate_swap(
                target_id,
                target,
                work_date,
                off_date,
                exclude_id=swap_id,
                check_past=False,
            )

        updated = (
            supabase_admin.table("saturday_swaps")
            .update(
                {
                    "status": data.status,
                    "approved_by": approver_employee_id,
                    "approved_date": datetime.now(timezone.utc).isoformat(),
                    "comments": data.comments,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", swap_id)
            .execute()
            .data[0]
        )

        record_audit_log(
            module="SATURDAY_SWAP",
            action=data.status.upper(),
            performed_by=auth_user_id,
            target_employee_id=target_id,
            record_id=swap_id,
            description=f"Saturday swap {data.status.lower()}"
            + (f" — {data.comments}" if data.comments else ""),
            old_values=existing,
            new_values=updated,
            request=request,
        )

        if get_preference(target_id, "leave_updates"):
            notify_employee(
                target_id,
                title=f"Saturday Swap {data.status}",
                message=(
                    f"Your request to work {_label(work_date)} instead of "
                    f"{_label(off_date)} has been {data.status.lower()}"
                    + (f" — {data.comments}" if data.comments else ".")
                ),
                notification_type="LEAVE",
            )

        _broadcast(data.status.lower(), target_id)
        return success_response(
            message=f"Saturday swap {data.status.lower()}.", data=updated
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update the Saturday swap.")


def cancel_swap(swap_id: str, auth_user_id: str, request: Optional[Request] = None):
    try:
        existing = _get_swap_or_404(swap_id)
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id or employee_id != existing["employee_id"]:
            forbidden("You can only cancel your own Saturday swap.")
        if existing["status"] not in LIVE_STATUSES:
            bad_request(f"A {existing['status'].lower()} request can't be cancelled.")

        if existing["status"] == "Approved":
            today = _today()
            work_date = date.fromisoformat(str(existing["work_date"])[:10])
            off_date = date.fromisoformat(str(existing["off_date"])[:10])
            if min(work_date, off_date) <= today:
                bad_request(
                    "This swap has already started, so it can't be cancelled. "
                    "Please contact HR."
                )

        updated = (
            supabase_admin.table("saturday_swaps")
            .update(
                {
                    "status": "Cancelled",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", swap_id)
            .execute()
            .data[0]
        )
        record_audit_log(
            module="SATURDAY_SWAP",
            action="CANCEL",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=swap_id,
            description="Saturday swap cancelled by employee",
            old_values=existing,
            new_values=updated,
            request=request,
        )
        _broadcast("cancelled", employee_id)
        return success_response(message="Saturday swap cancelled.", data=updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to cancel the Saturday swap.")


def _get_swap_or_404(swap_id: str) -> dict:
    rows = (
        supabase_admin.table("saturday_swaps")
        .select("*")
        .eq("id", swap_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        not_found("Saturday swap request not found.")
    return rows[0]
