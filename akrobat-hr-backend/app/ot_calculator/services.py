"""
OT Calculator (HR / Super Admin).

Auto OT comes from app/attendance/ot.py (clock time after shift end,
whole hours, leftover > 41 min rounds up). HR can override any day with a
manual value (table ot_adjustments); the final OT for a day is the manual
value when present, else the auto value.
"""

from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.attendance.ot import compute_ot
from app.attendance.services import _get_company_timezone
from app.attendance.tz_helper import resolve_record_timezone
from app.core.audit import record_audit_log
from app.core.database import supabase_admin
from app.core.exceptions import bad_request, internal_server_error
from app.core.logger import logger
from app.core.responses import success_response

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        year, mon = (int(p) for p in month.split("-"))
        first = date(year, mon, 1)
    except Exception:
        bad_request("month must look like 2026-10")
    return first, date(year, mon, monthrange(year, mon)[1])


def _local_hhmm(value, tz) -> Optional[str]:
    if not value:
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%H:%M")


def _hhmm(value) -> Optional[str]:
    return str(value)[:5] if value else None


def get_ot_month(month: str, employee_id: Optional[str] = None):
    try:
        first, last = _month_bounds(month)
        tz = _get_company_timezone()

        query = (
            supabase_admin.table("employees")
            .select(
                "id, employee_id, full_name, ot_weekday_end, ot_saturday_end, "
                "work_location, nationality"
            )
            .eq("ot_eligible", True)
        )
        if employee_id:
            query = query.eq("id", employee_id)
        staff = query.order("full_name").execute().data or []
        if not staff:
            return success_response(
                message="OT month fetched.", data={"month": month, "employees": []}
            )

        ids = [e["id"] for e in staff]
        att = (
            supabase_admin.table("attendance")
            .select(
                "employee_id, attendance_date, check_in_time, check_out_time, "
                "check_in_latitude, check_in_longitude, "
                "check_out_latitude, check_out_longitude"
            )
            .in_("employee_id", ids)
            .gte("attendance_date", first.isoformat())
            .lte("attendance_date", last.isoformat())
            .order("attendance_date")
            .execute()
            .data
            or []
        )
        adj = (
            supabase_admin.table("ot_adjustments")
            .select("employee_id, attendance_date, manual_ot_hours, note")
            .in_("employee_id", ids)
            .gte("attendance_date", first.isoformat())
            .lte("attendance_date", last.isoformat())
            .execute()
            .data
            or []
        )
        adj_by_key = {(a["employee_id"], a["attendance_date"]): a for a in adj}

        result = []
        for emp in staff:
            rows = []
            totals = {
                "after_shift_minutes": 0,
                "auto_ot_hours": 0,
                "final_ot_hours": 0.0,
            }
            for a in att:
                if a["employee_id"] != emp["id"]:
                    continue
                day = date.fromisoformat(a["attendance_date"])
                if day.weekday() == 6:  # no OT rule for Sunday
                    continue
                emp_tz = resolve_record_timezone(a, emp.get("work_location"), tz)
                ot = compute_ot(
                    day,
                    a.get("check_out_time"),
                    emp.get("ot_weekday_end"),
                    emp.get("ot_saturday_end"),
                    emp_tz,
                )
                adjustment = adj_by_key.get((emp["id"], a["attendance_date"]))
                manual = (
                    float(adjustment["manual_ot_hours"])
                    if adjustment and adjustment.get("manual_ot_hours") is not None
                    else None
                )
                final = manual if manual is not None else float(ot["ot_hours"])
                shift_end = (
                    emp.get("ot_saturday_end")
                    if day.weekday() == 5
                    else emp.get("ot_weekday_end")
                )
                rows.append(
                    {
                        "date": a["attendance_date"],
                        "weekday": WEEKDAYS[day.weekday()],
                        "shift_end": _hhmm(shift_end),
                        "timezone": emp_tz.key,
                        "check_out": _local_hhmm(a.get("check_out_time"), emp_tz),
                        "after_shift_minutes": ot["after_shift_minutes"],
                        "auto_ot_hours": ot["ot_hours"],
                        "manual_ot_hours": manual,
                        "note": (adjustment or {}).get("note"),
                        "final_ot_hours": final,
                    }
                )
                totals["after_shift_minutes"] += ot["after_shift_minutes"]
                totals["auto_ot_hours"] += ot["ot_hours"]
                totals["final_ot_hours"] += final

            result.append(
                {
                    "employee_id": emp["id"],
                    "employee_code": emp.get("employee_id"),
                    "full_name": emp.get("full_name"),
                    "weekday_end": _hhmm(emp.get("ot_weekday_end")),
                    "saturday_end": _hhmm(emp.get("ot_saturday_end")),
                    "rows": rows,
                    "totals": totals,
                }
            )

        return success_response(
            message="OT month fetched.", data={"month": month, "employees": result}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch OT data.")


def save_ot_adjustments(data, user, request: Optional[Request] = None):
    try:
        employee_ids = list({i.employee_id for i in data.items})
        eligible = (
            supabase_admin.table("employees")
            .select("id")
            .in_("id", employee_ids)
            .eq("ot_eligible", True)
            .execute()
            .data
            or []
        )
        eligible_ids = {e["id"] for e in eligible}
        if set(employee_ids) - eligible_ids:
            bad_request("One or more employees are not OT eligible.")

        to_upsert, to_delete = [], []
        for item in data.items:
            if item.manual_ot_hours is None:
                to_delete.append(item)
            else:
                to_upsert.append(
                    {
                        "employee_id": item.employee_id,
                        "attendance_date": item.attendance_date.isoformat(),
                        "manual_ot_hours": item.manual_ot_hours,
                        "note": (item.note or "").strip() or None,
                        "updated_by": user.id,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        if to_upsert:
            supabase_admin.table("ot_adjustments").upsert(
                to_upsert, on_conflict="employee_id,attendance_date"
            ).execute()
        for item in to_delete:
            (
                supabase_admin.table("ot_adjustments")
                .delete()
                .eq("employee_id", item.employee_id)
                .eq("attendance_date", item.attendance_date.isoformat())
                .execute()
            )

        record_audit_log(
            module="ATTENDANCE",
            action="OT_ADJUSTMENT",
            performed_by=user.id,
            description=f"OT adjusted for {len(data.items)} day(s)",
            new_values={"items": [i.model_dump(mode="json") for i in data.items]},
            request=request,
        )

        return success_response(
            message=f"Saved {len(data.items)} OT change(s).",
            data={"saved": len(to_upsert), "removed": len(to_delete)},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to save OT changes.")
