import json
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import wraps
from typing import Optional

from fastapi import HTTPException, Request

from app.core.audit import record_audit_log
from app.core.constants import ADMIN
from app.core.database import supabase_admin
from app.core.exceptions import bad_request, conflict, internal_server_error, not_found
from app.core.helpers.employee_helper import (
    get_employee_id_for_auth_user,
    get_employee_or_404,
)
from app.core.logger import logger
from app.core.responses import success_response

TABLE = "employee_resignations"

# employees.employment_status once the person has actually left.
# (During the notice period it stays "Active" -- they still work.)
RESIGNED = "Resigned"

SERVING = "Serving Notice"
RELIEVED = "Relieved"
WITHDRAWN = "Withdrawn"


# ==========================================
# helpers
# ==========================================


def _guard(message: str):
    """Same error handling used across the codebase: let HTTPExceptions
    through, log + 500 for everything else."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception(e)
                internal_server_error(message)

        return wrapper

    return deco


def _today() -> date:
    return date.today()


def _fetch_all(build, page_size: int = 1000) -> list:
    """Supabase caps a response at ~1000 rows; page through with range()."""
    rows, start = [], 0
    while True:
        chunk = build().range(start, start + page_size - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page_size:
            return rows
        start += page_size


def _require_resignation(employee_pk: str, include_withdrawn: bool = False) -> dict:
    """Latest non-withdrawn resignation row for this employee, or 404."""
    query = supabase_admin.table(TABLE).select("*").eq("employee_id", employee_pk)
    if not include_withdrawn:
        query = query.neq("status", WITHDRAWN)
    res = query.order("created_at", desc=True).limit(1).execute()
    if not res.data:
        not_found("Resignation record not found.")
    return res.data[0]


def _names(ids) -> dict:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    res = (
        supabase_admin.table("employees")
        .select("id, full_name")
        .in_("id", ids)
        .execute()
    )
    return {r["id"]: r["full_name"] for r in (res.data or [])}


def _role_of_employee(employee_pk: str) -> Optional[str]:
    res = (
        supabase_admin.table("user_profiles")
        .select("roles(role_name)")
        .eq("employee_id", employee_pk)
        .maybe_single()
        .execute()
    )
    if res and res.data and res.data.get("roles"):
        return res.data["roles"].get("role_name")
    return None


def _build_snapshot(employee_pk: str) -> dict:
    res = (
        supabase_admin.table("employees")
        .select(
            "employee_id, full_name, joining_date, manager_id, work_location,"
            " departments!employees_department_id_fkey(department_name),"
            " designations(designation_name)"
        )
        .eq("id", employee_pk)
        .single()
        .execute()
    )
    e = res.data or {}
    manager = _names([e.get("manager_id")]).get(e.get("manager_id"))
    return {
        "employee_code": e.get("employee_id"),
        "full_name": e.get("full_name"),
        "department": (e.get("departments") or {}).get("department_name"),
        "designation": (e.get("designations") or {}).get("designation_name"),
        "manager": manager,
        "joining_date": e.get("joining_date"),
        "work_location": e.get("work_location"),
    }


def _days_between(start: date, end: date) -> int:
    return (end - start).days


def _decorate(row: dict) -> dict:
    """Adds remaining notice days so the UI doesn't have to compute it."""
    lwd = date.fromisoformat(row["last_working_day"])
    row["notice_days_remaining"] = (
        max(0, (lwd - _today()).days) if row["status"] == SERVING else 0
    )
    return row


# ==========================================
# MARK AS RESIGNED
# ==========================================


@_guard("Unable to record resignation.")
def mark_resigned(data, current_user, request: Optional[Request] = None):
    employee = get_employee_or_404(data.employee_id)

    if employee.get("employment_status") == RESIGNED:
        conflict("This employee is already marked as resigned.")

    active = (
        supabase_admin.table(TABLE)
        .select("id")
        .eq("employee_id", data.employee_id)
        .neq("status", WITHDRAWN)
        .execute()
    )
    if active.data:
        conflict("A resignation is already recorded for this employee.")

    if data.last_working_day < data.resignation_date:
        bad_request("Last working day cannot be before the resignation date.")

    if _role_of_employee(data.employee_id) == ADMIN:
        bad_request("Super Admin accounts can't be marked as resigned here.")

    actor_employee_id = get_employee_id_for_auth_user(current_user.id)
    if actor_employee_id and actor_employee_id == data.employee_id:
        bad_request("You can't mark your own account as resigned.")

    row = {
        "employee_id": data.employee_id,
        "resignation_date": data.resignation_date.isoformat(),
        "last_working_day": data.last_working_day.isoformat(),
        "notice_period_days": _days_between(
            data.resignation_date, data.last_working_day
        ),
        "reason_category": data.reason_category,
        "reason_remarks": data.reason_remarks,
        "admin_remarks": data.admin_remarks,
        "eligible_for_rehire": data.eligible_for_rehire,
        "status": SERVING,
        "accepted_by": actor_employee_id,
        "snapshot": _build_snapshot(data.employee_id),
    }
    created = supabase_admin.table(TABLE).insert(row).execute().data[0]

    record_audit_log(
        module="RESIGNATION",
        action="CREATE",
        performed_by=getattr(current_user, "id", None),
        target_employee_id=data.employee_id,
        record_id=created["id"],
        description=f"{employee['full_name']} marked as resigned "
        f"(last working day {row['last_working_day']})",
        new_values=row,
        request=request,
    )

    # Last working day is today or already past -> relieve immediately.
    if data.last_working_day <= _today():
        _relieve(data.employee_id, current_user, request)
        created["status"] = RELIEVED

    return success_response(
        message="Resignation recorded.", data=_decorate(created), status_code=201
    )


# ==========================================
# RELIEVE (the step that actually removes access)
# ==========================================


def _relieve(employee_pk: str, current_user=None, request: Optional[Request] = None):
    """Turns a notice-period employee into an archived, resigned one.

    - employees.employment_status -> 'Resigned' (drops out of every list that
      filters on Active)
    - user_profiles.is_active -> False (auth/services.py already rejects login
      for inactive profiles)
    - Supabase auth user banned, so an existing session can't refresh
    - open site assignments closed (history kept)
    Nothing is deleted.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    profile = (
        supabase_admin.table("user_profiles")
        .select("auth_user_id")
        .eq("employee_id", employee_pk)
        .maybe_single()
        .execute()
    )

    supabase_admin.table("employees").update(
        {"employment_status": RESIGNED, "updated_at": now_iso}
    ).eq("id", employee_pk).execute()

    supabase_admin.table("user_profiles").update({"is_active": False}).eq(
        "employee_id", employee_pk
    ).execute()

    if profile and profile.data and profile.data.get("auth_user_id"):
        try:
            supabase_admin.auth.admin.update_user_by_id(
                profile.data["auth_user_id"], {"ban_duration": "876000h"}
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not ban auth user for {employee_pk}: {e}")

    try:
        supabase_admin.table("employee_site_assignments").update(
            {"is_active": False, "assigned_to": _today().isoformat()}
        ).eq("employee_id", employee_pk).eq("is_active", True).execute()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not close site assignments for {employee_pk}: {e}")

    row = _require_resignation(employee_pk)
    checklist = {**(row.get("exit_checklist") or {}), "access_disabled": True}
    supabase_admin.table(TABLE).update(
        {
            "status": RELIEVED,
            "relieved_at": now_iso,
            "exit_checklist": checklist,
            "updated_at": now_iso,
        }
    ).eq("id", row["id"]).execute()

    record_audit_log(
        module="RESIGNATION",
        action="RELIEVE",
        performed_by=getattr(current_user, "id", None),
        target_employee_id=employee_pk,
        record_id=row["id"],
        description="Employee relieved. Login disabled and moved to archive.",
        request=request,
    )


@_guard("Unable to relieve employee.")
def relieve_now(employee_pk: str, current_user, request: Optional[Request] = None):
    row = _require_resignation(employee_pk)
    if row["status"] != SERVING:
        bad_request("Only an employee serving notice can be relieved.")
    _relieve(employee_pk, current_user, request)
    return success_response(message="Employee relieved.")


def process_due_relievings():
    """Daily job (see main.py): relieves everyone whose last working day has
    arrived. Re-running is a safe no-op."""
    try:
        due = (
            supabase_admin.table(TABLE)
            .select("employee_id")
            .eq("status", SERVING)
            .lte("last_working_day", _today().isoformat())
            .execute()
            .data
            or []
        )
        for r in due:
            try:
                _relieve(r["employee_id"])
            except Exception as e:  # noqa: BLE001
                logger.error(f"Auto-relieve failed for {r['employee_id']}: {e}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"process_due_relievings failed: {e}")


@_guard("Unable to withdraw resignation.")
def withdraw_resignation(
    employee_pk: str, current_user, request: Optional[Request] = None
):
    row = _require_resignation(employee_pk)
    if row["status"] != SERVING:
        bad_request("Only a resignation in its notice period can be withdrawn.")

    supabase_admin.table(TABLE).update(
        {"status": WITHDRAWN, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", row["id"]).execute()

    record_audit_log(
        module="RESIGNATION",
        action="WITHDRAW",
        performed_by=getattr(current_user, "id", None),
        target_employee_id=employee_pk,
        record_id=row["id"],
        description="Resignation withdrawn during notice period.",
        request=request,
    )
    return success_response(message="Resignation withdrawn.")


# ==========================================
# LIST + DETAIL
# ==========================================


@_guard("Unable to fetch resigned employees.")
def list_resignations(
    status: Optional[str] = None,
    department: Optional[str] = None,
    year: Optional[int] = None,
    search: Optional[str] = None,
):
    rows = (
        supabase_admin.table(TABLE)
        .select(
            "*, employee:employees!employee_resignations_employee_id_fkey"
            "(employee_id, full_name, email, profile_photo)"
        )
        .neq("status", WITHDRAWN)
        .order("resignation_date", desc=True)
        .execute()
        .data
        or []
    )
    rows = [_decorate(r) for r in rows]

    this_year = _today().year
    stats = {
        "total": len(rows),
        "serving_notice": sum(r["status"] == SERVING for r in rows),
        "this_year": sum(r["resignation_date"][:4] == str(this_year) for r in rows),
        "settlement_pending": sum(r["settlement_status"] != "Paid" for r in rows),
    }
    departments = sorted(
        {(r.get("snapshot") or {}).get("department") for r in rows} - {None}
    )

    if status:
        rows = [r for r in rows if r["status"] == status]
    if department:
        rows = [
            r for r in rows if (r.get("snapshot") or {}).get("department") == department
        ]
    if year:
        rows = [r for r in rows if r["resignation_date"][:4] == str(year)]
    if search:
        q = search.strip().lower()
        rows = [
            r
            for r in rows
            if q in (r.get("employee") or {}).get("full_name", "").lower()
            or q in (r.get("employee") or {}).get("employee_id", "").lower()
            or q in ((r.get("employee") or {}).get("email") or "").lower()
        ]

    return success_response(
        message="Resigned employees fetched.",
        data={"items": rows, "stats": stats, "departments": departments},
    )


@_guard("Unable to fetch resignation.")
def get_resignation(employee_pk: str):
    row = _require_resignation(employee_pk)
    emp = (
        supabase_admin.table("employees")
        .select("id, employee_id, full_name, email, profile_photo, joining_date")
        .eq("id", employee_pk)
        .single()
        .execute()
        .data
    )
    row["employee"] = emp
    row["accepted_by_name"] = _names([row.get("accepted_by")]).get(
        row.get("accepted_by")
    )
    return success_response(message="Fetched.", data=_decorate(row))


# ==========================================
# UPDATE (remarks, checklist, settlement, last working day)
# ==========================================


@_guard("Unable to update resignation.")
def update_resignation(
    employee_pk: str, data, current_user, request: Optional[Request] = None
):
    row = _require_resignation(employee_pk)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        bad_request("Nothing to update.")

    if "last_working_day" in changes:
        if row["status"] != SERVING:
            bad_request(
                "Last working day can only be changed during the notice period."
            )
        lwd = changes["last_working_day"]
        if lwd < date.fromisoformat(row["resignation_date"]):
            bad_request("Last working day cannot be before the resignation date.")
        changes["last_working_day"] = lwd.isoformat()
        changes["notice_period_days"] = _days_between(
            date.fromisoformat(row["resignation_date"]), lwd
        )

    if "settlement_paid_on" in changes and changes["settlement_paid_on"]:
        changes["settlement_paid_on"] = changes["settlement_paid_on"].isoformat()

    if changes.get("settlement_status") not in (None, "Pending", "Paid"):
        bad_request("settlement_status must be Pending or Paid.")

    if "exit_checklist" in changes:
        changes["exit_checklist"] = {
            **(row.get("exit_checklist") or {}),
            **changes["exit_checklist"],
        }

    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = (
        supabase_admin.table(TABLE)
        .update(changes)
        .eq("id", row["id"])
        .execute()
        .data[0]
    )

    record_audit_log(
        module="RESIGNATION",
        action="UPDATE",
        performed_by=getattr(current_user, "id", None),
        target_employee_id=employee_pk,
        record_id=row["id"],
        description="Resignation record updated.",
        old_values={k: row.get(k) for k in changes},
        new_values={k: updated.get(k) for k in changes},
        request=request,
    )

    # Moving the last working day to today/earlier relieves immediately.
    if (
        updated["status"] == SERVING
        and date.fromisoformat(updated["last_working_day"]) <= _today()
    ):
        _relieve(employee_pk, current_user, request)
        updated["status"] = RELIEVED

    return success_response(message="Updated.", data=_decorate(updated))


# ==========================================
# READ-ONLY TABS
# ==========================================


@_guard("Unable to fetch profile.")
def get_profile_tab(employee_pk: str):
    _require_resignation(employee_pk)
    emp = (
        supabase_admin.table("employees")
        .select(
            "*, departments!employees_department_id_fkey(department_name),"
            " designations(designation_name), shifts(shift_name)"
        )
        .eq("id", employee_pk)
        .single()
        .execute()
        .data
    )
    emp["manager_name"] = _names([emp.get("manager_id")]).get(emp.get("manager_id"))

    emergency = (
        supabase_admin.table("employee_emergency_contacts")
        .select("*")
        .eq("employee_id", employee_pk)
        .execute()
        .data
        or []
    )
    sites = (
        supabase_admin.table("employee_site_assignments")
        .select("*, locations(location_name)")
        .eq("employee_id", employee_pk)
        .order("assigned_from", desc=True)
        .execute()
        .data
        or []
    )
    names = _names([s.get("assigned_by") for s in sites])
    for s in sites:
        s["assigned_by_name"] = names.get(s.get("assigned_by"))

    return success_response(
        message="Fetched.",
        data={
            "employee": emp,
            "emergency_contacts": emergency,
            "site_assignments": sites,
        },
    )


@_guard("Unable to fetch attendance.")
def get_attendance_tab(employee_pk: str, month: Optional[str], status: Optional[str]):
    _require_resignation(employee_pk)
    cols = (
        "attendance_date, check_in_time, check_out_time, working_minutes,"
        " late_minutes, overtime_minutes, status"
    )
    rows = _fetch_all(
        lambda: supabase_admin.table("attendance")
        .select(cols)
        .eq("employee_id", employee_pk)
        .order("attendance_date", desc=True)
    )

    worked = [r for r in rows if r.get("check_in_time")]
    summary = {
        "present_days": len(worked),
        "absent_days": sum((r.get("status") or "").lower() == "absent" for r in rows),
        "late_marks": sum((r.get("late_minutes") or 0) > 0 for r in rows),
        "overtime_hours": round(
            sum(r.get("overtime_minutes") or 0 for r in rows) / 60, 1
        ),
        "avg_hours_per_day": (
            round(
                sum(r.get("working_minutes") or 0 for r in worked) / 60 / len(worked), 1
            )
            if worked
            else 0
        ),
    }

    monthly = defaultdict(
        lambda: {"present": 0, "absent": 0, "late": 0, "ot_hours": 0.0}
    )
    for r in rows:
        m = monthly[r["attendance_date"][:7]]
        m["present"] += 1 if r.get("check_in_time") else 0
        m["absent"] += 1 if (r.get("status") or "").lower() == "absent" else 0
        m["late"] += 1 if (r.get("late_minutes") or 0) > 0 else 0
        m["ot_hours"] += (r.get("overtime_minutes") or 0) / 60
    monthly_list = [
        {"month": k, **{**v, "ot_hours": round(v["ot_hours"], 1)}}
        for k, v in sorted(monthly.items(), reverse=True)
    ]

    table = rows
    if month:
        table = [r for r in table if r["attendance_date"].startswith(month)]
    if status:
        table = [r for r in table if (r.get("status") or "").lower() == status.lower()]

    return success_response(
        message="Fetched.",
        data={"summary": summary, "monthly": monthly_list, "records": table[:400]},
    )


@_guard("Unable to fetch leaves.")
def get_leaves_tab(employee_pk: str):
    _require_resignation(employee_pk)
    balances = (
        supabase_admin.table("leave_balances")
        .select("total_days, used_days, remaining_days, year, leave_types(leave_name)")
        .eq("employee_id", employee_pk)
        .order("year", desc=True)
        .execute()
        .data
        or []
    )
    requests = (
        supabase_admin.table("leave_requests")
        .select("*, leave_types(leave_name)")
        .eq("employee_id", employee_pk)
        .order("start_date", desc=True)
        .execute()
        .data
        or []
    )
    names = _names([r.get("approved_by") for r in requests])
    for r in requests:
        r["approved_by_name"] = names.get(r.get("approved_by"))
    return success_response(
        message="Fetched.", data={"balances": balances, "requests": requests}
    )


@_guard("Unable to fetch payroll.")
def get_payroll_tab(employee_pk: str):
    _require_resignation(employee_pk)
    rows = (
        supabase_admin.table("payroll")
        .select("*")
        .eq("employee_id", employee_pk)
        .order("payroll_year", desc=True)
        .order("payroll_month", desc=True)
        .execute()
        .data
        or []
    )
    totals = {
        "payslips": len(rows),
        "total_net": round(sum(float(r.get("net_salary") or 0) for r in rows), 2),
        "total_overtime": round(
            sum(float(r.get("overtime_amount") or 0) for r in rows), 2
        ),
    }
    return success_response(
        message="Fetched.", data={"records": rows, "totals": totals}
    )


@_guard("Unable to fetch documents.")
def get_documents_tab(employee_pk: str):
    _require_resignation(employee_pk)
    docs = (
        supabase_admin.table("documents")
        .select("*")
        .eq("employee_id", employee_pk)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    return success_response(message="Fetched.", data=docs)


@_guard("Unable to fetch audit trail.")
def get_audit_tab(employee_pk: str):
    _require_resignation(employee_pk)
    # record_audit_log() stores target_employee_id inside the JSON text of
    # `description`, so match on that (plus rows whose record_id is the employee).
    rows = (
        supabase_admin.table("audit_logs")
        .select("*, actor:employees(full_name)")
        .or_(f"record_id.eq.{employee_pk},description.ilike.%{employee_pk}%")
        .order("created_at", desc=True)
        .limit(300)
        .execute()
        .data
        or []
    )
    out = []
    for r in rows:
        message = r.get("description")
        try:
            message = json.loads(message).get("message", message)
        except Exception:  # noqa: BLE001
            pass
        out.append(
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "module": r["module"],
                "action": r["action"],
                "message": message,
                "performed_by": (r.get("actor") or {}).get("full_name"),
                "ip_address": r.get("ip_address"),
            }
        )
    return success_response(message="Fetched.", data=out)
