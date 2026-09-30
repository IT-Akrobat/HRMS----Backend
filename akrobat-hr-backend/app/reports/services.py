from datetime import date, timedelta

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.helpers.employee_helper import is_operation_every_saturday_name


def _tenure(joining_date):
    """ "How long worked" as of today, from employees.joining_date.
    Returns {years, months, label} (label e.g. "2 yrs 3 mos", "7 mos",
    "< 1 mo") or None if there's no joining_date to work from -- used by
    the Employees report/export ("Tenure" column) and the
    single-employee full report."""

    if not joining_date:
        return None

    try:
        start = (
            joining_date
            if isinstance(joining_date, date)
            else date.fromisoformat(str(joining_date)[:10])
        )
    except (ValueError, TypeError):
        return None

    today = date.today()
    if start > today:
        return None

    months = (today.year - start.year) * 12 + (today.month - start.month)
    if today.day < start.day:
        months -= 1
    months = max(months, 0)
    years, rem_months = divmod(months, 12)

    if years == 0 and rem_months == 0:
        label = "< 1 mo"
    else:
        parts = []
        if years:
            parts.append(f"{years} yr{'s' if years != 1 else ''}")
        if rem_months or not years:
            parts.append(f"{rem_months} mo{'s' if rem_months != 1 else ''}")
        label = " ".join(parts)

    return {"years": years, "months": rem_months, "label": label}


# =========================
# EMPLOYEE REPORT
# =========================


def employee_report():

    try:

        # NOTE: departments/designations don't have a "name" column (it's
        # department_name / designation_name — see sql/001_schema.sql), and
        # employees has no direct FK to roles (role lives on user_profiles),
        # so the previous embed here would fail at the PostgREST layer.
        #
        # departments(department_name) is also ambiguous on its own: there
        # are two FKs between employees and departments — the normal
        # employees.department_id -> departments.id, and
        # departments.manager_id -> employees.id (the department's manager).
        # PostgREST needs the explicit FK name to know which one to walk.
        #
        # employees.manager_id -> employees.id (the employee's own reporting
        # manager, set on create/update — see app/employees/services.py) is
        # a self-referencing FK, and unlike departments_manager_id_fkey it
        # isn't in PostgREST's schema cache under any name PostgREST will
        # accept as an embed hint (confirmed by PGRST200 in practice) —
        # so it's resolved below as a plain Python dict lookup against the
        # employee list already being fetched, same as employee_full_report()
        # does for the department's manager, rather than trusted to PostgREST.
        #
        # This mirrors every field shown on the "My Profile" page (Job
        # Details tab: designation, department, employment status, joining
        # date, work location, reporting manager, shift) plus phone/email —
        # for the "Employees" tab of the Reports page — with sites worked
        # and lifetime attendance totals merged in below, same as
        # employee_full_report() does for a single employee.
        response = supabase_admin.table("employees").select("""
            *,
            departments!employees_department_id_fkey(department_name),
            designations(designation_name),
            shifts(shift_name, start_time, end_time)
            """).execute()

        employees = response.data or []

        # Reporting manager — plain lookup against the roster we already
        # have in memory, keyed by employees.id (manager_id points there).
        employees_by_id = {e["id"]: e for e in employees if e.get("id")}

        # Every site visit ever logged, for every employee — grouped by
        # employee then by location, same shape as employee_full_report()'s
        # "sites_worked" but for the whole roster in one pass instead of
        # one query per employee.
        visits_resp = (
            supabase_admin.table("attendance_site_visits")
            .select(
                "employee_id, location_id, duration_minutes, locations(location_name)"
            )
            .execute()
        )
        sites_by_employee = {}
        for v in visits_resp.data or []:
            emp_id = v.get("employee_id")
            if not emp_id:
                continue
            loc_id = v.get("location_id") or "unknown"
            loc_name = (v.get("locations") or {}).get("location_name") or "Unknown Site"
            bucket = sites_by_employee.setdefault(emp_id, {})
            entry = bucket.setdefault(
                loc_id,
                {"location_name": loc_name, "visit_count": 0, "total_minutes": 0},
            )
            entry["visit_count"] += 1
            entry["total_minutes"] += v.get("duration_minutes") or 0

        # Lifetime attendance totals, grouped by employee — same fields as
        # employee_full_report()'s "attendance_summary".
        attendance_resp = (
            supabase_admin.table("attendance")
            .select(
                "employee_id, working_minutes, break_minutes, overtime_minutes, status"
            )
            .execute()
        )
        attendance_by_employee = {}
        for a in attendance_resp.data or []:
            emp_id = a.get("employee_id")
            if not emp_id:
                continue
            bucket = attendance_by_employee.setdefault(
                emp_id,
                {
                    "total_days_recorded": 0,
                    "present_days": 0,
                    "absent_days": 0,
                    "total_working_minutes": 0,
                    "total_break_minutes": 0,
                    "total_overtime_minutes": 0,
                },
            )
            bucket["total_days_recorded"] += 1
            if a.get("status") in ("Present", "Half Day"):
                bucket["present_days"] += 1
            elif a.get("status") == "Absent":
                bucket["absent_days"] += 1
            bucket["total_working_minutes"] += a.get("working_minutes") or 0
            bucket["total_break_minutes"] += a.get("break_minutes") or 0
            bucket["total_overtime_minutes"] += a.get("overtime_minutes") or 0

        for e in employees:
            emp_id = e.get("id")
            sites_worked = sorted(
                sites_by_employee.get(emp_id, {}).values(),
                key=lambda s: -s["total_minutes"],
            )
            e["sites_worked"] = sites_worked
            e["distinct_site_count"] = len(sites_worked)
            e["total_site_visit_minutes"] = sum(
                s["total_minutes"] for s in sites_worked
            )
            e["tenure"] = _tenure(e.get("joining_date"))
            e["attendance_summary"] = attendance_by_employee.get(
                emp_id,
                {
                    "total_days_recorded": 0,
                    "present_days": 0,
                    "absent_days": 0,
                    "total_working_minutes": 0,
                    "total_break_minutes": 0,
                    "total_overtime_minutes": 0,
                },
            )

            manager = employees_by_id.get(e.get("manager_id"))
            e["manager"] = (
                {
                    "full_name": manager.get("full_name"),
                    "employee_id": manager.get("employee_id"),
                }
                if manager
                else None
            )

        return success_response(
            message="Employee report fetched successfully", data=employees
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# ATTENDANCE REPORT
# =========================


def attendance_report():

    try:

        response = supabase_admin.table("attendance").select("""
            *,
            employees(
                full_name,
                employee_id,
                profile_photo
            )
            """).order("attendance_date", desc=True).execute()

        return success_response(
            message="Attendance report fetched successfully", data=response.data
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# TODAY ATTENDANCE
# =========================


def today_attendance():

    try:

        today = str(date.today())

        response = supabase_admin.table("attendance").select("""
            *,
            employees(
                full_name,
                employee_id,
                profile_photo
            )
            """).eq("attendance_date", today).execute()

        return success_response(
            message="Today's attendance fetched successfully", data=response.data
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# LEAVE REPORT
# =========================


def leave_report():

    try:

        # NOTE: schema table is "leave_requests" (see sql/001_schema.sql) —
        # this previously queried a non-existent "leaves" table, which made
        # GET /reports/leaves fail with a 500 on every call.
        # leave_requests has TWO foreign keys to employees (employee_id —
        # who's requesting — and approved_by — who approved it), so a bare
        # "employees(...)" embed is ambiguous to PostgREST (PGRST201: "more
        # than one relationship was found for 'leave_requests' and
        # 'employees'"). Named explicitly here, same convention as the
        # departments<->employees embeds in employee_report()/
        # employee_full_report() above.
        response = supabase_admin.table("leave_requests").select("""
            *,
            employees!leave_requests_employee_id_fkey(
                full_name,
                employee_id,
                profile_photo
            )
            """).execute()

        return success_response(
            message="Leave report fetched successfully", data=response.data
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# PAYROLL REPORT
# =========================


def payroll_report():

    try:

        response = supabase_admin.table("payroll").select("""
            *,
            employees(
                full_name,
                employee_id,
                profile_photo
            )
            """).execute()

        return success_response(
            message="Payroll report fetched successfully", data=response.data
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# PROJECT REPORT
# =========================


def project_report():

    try:

        response = supabase_admin.table("projects").select("*").execute()

        return success_response(
            message="Project report fetched successfully", data=response.data
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# DASHBOARD REPORT
# =========================


def dashboard_report():

    try:

        employees = len(supabase_admin.table("employees").select("id").execute().data)

        attendance = len(supabase_admin.table("attendance").select("id").execute().data)

        leaves = len(supabase_admin.table("leave_requests").select("id").execute().data)

        payroll = len(supabase_admin.table("payroll").select("id").execute().data)

        projects = len(supabase_admin.table("projects").select("id").execute().data)

        return success_response(
            message="Dashboard report fetched successfully",
            data={
                "employees": employees,
                "attendance": attendance,
                "leaves": leaves,
                "payroll": payroll,
                "projects": projects,
            },
        )

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# SINGLE EMPLOYEE — FULL REPORT
# =========================
# Everything about one employee for a downloadable report: profile,
# department/designation, who they report to (the department's
# manager_id -> employees.full_name), a breakdown of every site they've
# logged a visit to (attendance_site_visits, grouped by location) with
# how many distinct sites and total time at each, and lifetime
# attendance totals (working/break/overtime minutes).


def employee_full_report(employee_id: str):

    try:

        emp_resp = supabase_admin.table("employees").select("""
                *,
                departments!employees_department_id_fkey(department_name, manager_id),
                designations(designation_name)
                """).eq("id", employee_id).maybe_single().execute()
        employee = emp_resp.data if emp_resp else None

        if not employee:
            raise HTTPException(404, "Employee not found.")

        # "Under whom" — the department's manager, looked up separately
        # rather than as a nested embed, since PostgREST needs an explicit
        # FK name for the *second* employees<->departments relationship
        # (departments.manager_id -> employees.id) and stacking that two
        # levels deep in one select string is brittle. A plain follow-up
        # query is simpler and just as fast for a single row.
        manager_name = None
        manager_employee_code = None
        manager_id = (employee.get("departments") or {}).get("manager_id")
        if manager_id and manager_id != employee_id:
            mgr_resp = (
                supabase_admin.table("employees")
                .select("full_name, employee_id")
                .eq("id", manager_id)
                .maybe_single()
                .execute()
            )
            if mgr_resp and mgr_resp.data:
                manager_name = mgr_resp.data.get("full_name")
                manager_employee_code = mgr_resp.data.get("employee_id")

        # Every site visit this employee has ever logged, grouped by
        # location — "how many sites worked" and "how long at each".
        visits_resp = (
            supabase_admin.table("attendance_site_visits")
            .select(
                "location_id, duration_minutes, arrival_time, locations(location_name, address)"
            )
            .eq("employee_id", employee_id)
            .execute()
        )
        visits = visits_resp.data or []

        sites_by_id = {}
        for v in visits:
            loc_id = v.get("location_id") or "unknown"
            loc = v.get("locations") or {}
            loc_name = loc.get("location_name") or "Unknown Site"
            loc_address = loc.get("address") or "—"
            entry = sites_by_id.setdefault(
                loc_id,
                {
                    "location_name": loc_name,
                    "location_address": loc_address,
                    "visit_count": 0,
                    "total_minutes": 0,
                    "dates_worked": set(),
                },
            )
            entry["visit_count"] += 1
            # Still-open visits (no departure yet) have duration_minutes =
            # null — counted as a visit, contributes 0 minutes until closed.
            entry["total_minutes"] += v.get("duration_minutes") or 0
            # arrival_time looks like "2026-07-15T09:00:00" — just the date
            # part is what "which day did they work this site" means here.
            arrival = v.get("arrival_time")
            if arrival:
                entry["dates_worked"].add(arrival[:10])

        sites_worked = sorted(sites_by_id.values(), key=lambda s: -s["total_minutes"])
        for s in sites_worked:
            s["dates_worked"] = sorted(s["dates_worked"])

        # Same visits, bucketed by calendar month ("2026-07") and by year
        # ("2026") instead of by site — "how many distinct sites did they
        # work in this month/year, and for how long" (arrival_time's date
        # is what a visit is attributed to, same as the site breakdown
        # above uses duration regardless of whether it spans midnight).
        monthly_by_key = {}
        yearly_by_key = {}
        for v in visits:
            arrival = v.get("arrival_time")
            if not arrival:
                continue
            month_key = arrival[:7]  # "2026-07-15T09:00:00" -> "2026-07"
            year_key = arrival[:4]  # -> "2026"
            loc_id = v.get("location_id") or "unknown"
            loc_name = (v.get("locations") or {}).get("location_name") or "Unknown Site"
            minutes = v.get("duration_minutes") or 0

            for bucket_by_key, key in (
                (monthly_by_key, month_key),
                (yearly_by_key, year_key),
            ):
                bucket = bucket_by_key.setdefault(
                    key, {"period": key, "sites": {}, "total_minutes": 0}
                )
                bucket["total_minutes"] += minutes
                site_entry = bucket["sites"].setdefault(
                    loc_id,
                    {"location_name": loc_name, "visit_count": 0, "total_minutes": 0},
                )
                site_entry["visit_count"] += 1
                site_entry["total_minutes"] += minutes

        def _finalize_periods(bucket_by_key):
            periods = []
            for key in sorted(bucket_by_key.keys()):
                b = bucket_by_key[key]
                site_list = sorted(
                    b["sites"].values(), key=lambda s: -s["total_minutes"]
                )
                periods.append(
                    {
                        "period": b["period"],
                        "distinct_site_count": len(site_list),
                        "site_names": [s["location_name"] for s in site_list],
                        "total_minutes": b["total_minutes"],
                    }
                )
            return periods

        monthly_sites = _finalize_periods(monthly_by_key)
        yearly_sites = _finalize_periods(yearly_by_key)

        # Lifetime attendance totals.
        attendance_resp = (
            supabase_admin.table("attendance")
            .select("working_minutes, break_minutes, overtime_minutes, status")
            .eq("employee_id", employee_id)
            .execute()
        )
        attendance_rows = attendance_resp.data or []

        data = {
            **employee,
            "manager_name": manager_name,
            "manager_employee_code": manager_employee_code,
            "tenure": _tenure(employee.get("joining_date")),
            "sites_worked": sites_worked,
            "distinct_site_count": len(sites_worked),
            "total_site_visit_minutes": sum(s["total_minutes"] for s in sites_worked),
            "monthly_sites": monthly_sites,
            "yearly_sites": yearly_sites,
            "attendance_summary": {
                "total_days_recorded": len(attendance_rows),
                "present_days": sum(
                    1
                    for r in attendance_rows
                    if r.get("status") in ("Present", "Half Day")
                ),
                "absent_days": sum(
                    1 for r in attendance_rows if r.get("status") == "Absent"
                ),
                "total_working_minutes": sum(
                    (r.get("working_minutes") or 0) for r in attendance_rows
                ),
                "total_break_minutes": sum(
                    (r.get("break_minutes") or 0) for r in attendance_rows
                ),
                "total_overtime_minutes": sum(
                    (r.get("overtime_minutes") or 0) for r in attendance_rows
                ),
            },
        }

        return success_response(
            message="Employee full report fetched successfully", data=data
        )

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# FULL-CALENDAR HELPERS (Excel monthly attendance)
# =========================
# The monthly Excel export must list EVERY date of the month, not just
# the days that have an attendance row. For each date we work out a
# day_type:
#   "Record" -- normal day: use the attendance row (may be missing ->
#               the export leaves the cells empty)
#   "Holiday"-- public holiday (holidays table, observed date) on a
#               working day -> Status says "Holiday (<name>)", rest empty
#   "Leave"  -- employee has an Approved leave covering that date
#   "Off"    -- Sunday, or a Saturday this employee doesn't work
#               (works_saturday = false, or alternate_saturday = true
#               and it isn't the 2nd/4th Saturday) -> export leaves the
#               whole row empty (date only)
# A day on which the employee actually checked in always stays a
# "Record", so real work is never hidden by these rules. Priority when
# rules overlap: worked > Off > Holiday > Leave (a leave that falls on a
# holiday just shows as the holiday).


def _is_second_or_fourth_saturday(d: date) -> bool:
    return ((d.day - 1) // 7 + 1) in (2, 4)


def _is_off_day(d: date, works_saturday: bool, alternate_saturday: bool) -> bool:
    if d.weekday() == 6:  # Sunday -- everyone is off
        return True
    if d.weekday() == 5:  # Saturday -- depends on the employee
        if not works_saturday:
            return True
        if alternate_saturday and not _is_second_or_fourth_saturday(d):
            return True
    return False


def _saturday_flags(emp: dict) -> tuple[bool, bool]:
    """
    (works_saturday, alternate_saturday) for an employees row. OPERATION
    department staff work EVERY Saturday (8:00-3:30) -- no alternate
    Saturday -- regardless of what the stored flags say. Operation PROJECT
    MANAGER is exempt and follows their own stored flags.
    """
    dept = emp.get("departments") or {}
    desig = emp.get("designations") or {}
    if is_operation_every_saturday_name(
        dept.get("department_name"), desig.get("designation_name")
    ):
        return True, False
    return bool(emp.get("works_saturday")), bool(emp.get("alternate_saturday"))


def _leave_dates_in_range(leave_rows, start: date, end: date) -> set:
    dates = set()
    for row in leave_rows or []:
        try:
            ls = max(date.fromisoformat(str(row["start_date"])[:10]), start)
            le = min(date.fromisoformat(str(row["end_date"])[:10]), end)
        except (KeyError, ValueError, TypeError):
            continue
        d = ls
        while d <= le:
            dates.add(d)
            d += timedelta(days=1)
    return dates


def _holidays_in_range(start: date, end: date) -> dict:
    """{date: holiday_name} for public holidays in start..end. Uses the
    observed date (holidays.holiday_date -- already Sunday->Monday
    shifted). Employees aren't tagged with a country, so every
    holiday row applies to everyone (same as the holiday reminders)."""
    rows = (
        supabase_admin.table("holidays")
        .select("holiday_name, holiday_date")
        .gte("holiday_date", start.isoformat())
        .lte("holiday_date", end.isoformat())
        .execute()
        .data
        or []
    )
    out = {}
    for r in rows:
        try:
            d = date.fromisoformat(str(r["holiday_date"])[:10])
        except (KeyError, ValueError, TypeError):
            continue
        out.setdefault(d, (r.get("holiday_name") or "").strip())
    return out


def _build_month_days(
    start: date,
    end: date,
    records,
    leave_dates: set,
    works_saturday: bool,
    alternate_saturday: bool,
    holidays: dict | None = None,
):
    """One entry per calendar day from start..end (inclusive)."""
    holidays = holidays or {}
    by_date = {str(r.get("attendance_date"))[:10]: r for r in (records or [])}
    days = []
    d = start
    while d <= end:
        rec = by_date.get(d.isoformat())
        worked = bool(rec and rec.get("check_in_time"))
        if worked:
            day_type = "Record"
        elif _is_off_day(d, works_saturday, alternate_saturday):
            day_type = "Off"
        elif d in holidays:
            day_type = "Holiday"
        elif d in leave_dates:
            day_type = "Leave"
        else:
            day_type = "Record"
        days.append(
            {
                "attendance_date": d.isoformat(),
                "day_type": day_type,
                "holiday_name": holidays.get(d) if day_type == "Holiday" else None,
                "record": rec if day_type == "Record" else None,
            }
        )
        d += timedelta(days=1)
    return days


def _month_bounds(month: str):
    try:
        year_str, month_str = month.split("-")
        year, month_num = int(year_str), int(month_str)
        if not (1 <= month_num <= 12):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "month must be in YYYY-MM format, e.g. 2026-07.")
    start = date(year, month_num, 1)
    end = (
        date(year + 1, 1, 1) if month_num == 12 else date(year, month_num + 1, 1)
    ) - timedelta(days=1)
    return start, end


def _fetch_all(build_query, page_size: int = 1000):
    """Supabase caps a response at ~1000 rows; page through them all."""
    rows, offset = [], 0
    while True:
        chunk = build_query().range(offset, offset + page_size - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page_size:
            return rows
        offset += page_size


# =========================
# SINGLE EMPLOYEE — MONTHLY ATTENDANCE
# =========================
# One employee, one calendar month: every day's record plus the month's
# totals (working hours, break time, overtime, lates) — for the
# "download this employee's monthly attendance" action.


def employee_monthly_attendance_report(employee_id: str, month: str):

    try:

        start, end = _month_bounds(month)

        emp_resp = supabase_admin.table("employees").select("""
                full_name, employee_id, works_saturday, alternate_saturday,
                departments!employees_department_id_fkey(department_name),
                designations(designation_name)
                """).eq("id", employee_id).maybe_single().execute()
        employee = emp_resp.data if emp_resp else None

        if not employee:
            raise HTTPException(404, "Employee not found.")

        att_resp = (
            supabase_admin.table("attendance")
            .select("*")
            .eq("employee_id", employee_id)
            .gte("attendance_date", start.isoformat())
            .lte("attendance_date", end.isoformat())
            .order("attendance_date")
            .execute()
        )
        rows = att_resp.data or []

        leave_resp = (
            supabase_admin.table("leave_requests")
            .select("start_date, end_date")
            .eq("employee_id", employee_id)
            .eq("status", "Approved")
            .lte("start_date", end.isoformat())
            .gte("end_date", start.isoformat())
            .execute()
        )
        leave_dates = _leave_dates_in_range(leave_resp.data, start, end)

        works_sat, alt_sat = _saturday_flags(employee)
        days = _build_month_days(
            start,
            end,
            rows,
            leave_dates,
            works_sat,
            alt_sat,
            _holidays_in_range(start, end),
        )

        data = {
            "employee": employee,
            "month": month,
            "from_date": start.isoformat(),
            "to_date": end.isoformat(),
            "records": rows,
            # Every date of the month with its day_type (Record / Leave /
            # Holiday / Off) -- this is what the Excel export iterates over.
            "days": days,
            "summary": {
                "present_days": sum(1 for r in rows if r.get("status") == "Present"),
                "half_days": sum(1 for r in rows if r.get("status") == "Half Day"),
                "absent_days": sum(1 for r in rows if r.get("status") == "Absent"),
                "total_working_minutes": sum(
                    (r.get("working_minutes") or 0) for r in rows
                ),
                "total_break_minutes": sum((r.get("break_minutes") or 0) for r in rows),
                "total_overtime_minutes": sum(
                    (r.get("overtime_minutes") or 0) for r in rows
                ),
                "total_late_minutes": sum((r.get("late_minutes") or 0) for r in rows),
            },
        }

        return success_response(
            message="Employee monthly attendance fetched successfully", data=data
        )

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# ALL EMPLOYEES — MONTHLY ATTENDANCE (full calendar)
# =========================
# Powers the Attendance tab's month-only Excel download: every employee,
# every date of the month (see FULL-CALENDAR HELPERS above).


def all_employees_monthly_attendance_report(month: str):

    try:

        start, end = _month_bounds(month)

        employees = _fetch_all(
            lambda: supabase_admin.table("employees")
            .select(
                "id, full_name, employee_id, works_saturday, alternate_saturday, "
                "departments!employees_department_id_fkey(department_name), "
                "designations(designation_name)"
            )
            .order("full_name")
        )

        attendance = _fetch_all(
            lambda: supabase_admin.table("attendance")
            .select("*")
            .gte("attendance_date", start.isoformat())
            .lte("attendance_date", end.isoformat())
            .order("attendance_date")
        )

        leaves = _fetch_all(
            lambda: supabase_admin.table("leave_requests")
            .select("employee_id, start_date, end_date")
            .eq("status", "Approved")
            .lte("start_date", end.isoformat())
            .gte("end_date", start.isoformat())
        )

        holidays = _holidays_in_range(start, end)

        att_by_emp, leave_by_emp = {}, {}
        for r in attendance:
            att_by_emp.setdefault(r.get("employee_id"), []).append(r)
        for r in leaves:
            leave_by_emp.setdefault(r.get("employee_id"), []).append(r)

        result = []
        for emp in employees:
            emp_id = emp["id"]
            result.append(
                {
                    "employee": {
                        "full_name": emp.get("full_name"),
                        "employee_id": emp.get("employee_id"),
                    },
                    "days": _build_month_days(
                        start,
                        end,
                        att_by_emp.get(emp_id, []),
                        _leave_dates_in_range(leave_by_emp.get(emp_id, []), start, end),
                        *_saturday_flags(emp),
                        holidays,
                    ),
                }
            )

        return success_response(
            message="Monthly attendance for all employees fetched successfully",
            data={"month": month, "employees": result},
        )

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(500, str(e))
