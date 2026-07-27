from datetime import date, timedelta

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response


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
                employee_id
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
                employee_id
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
                employee_id
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
                employee_id
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
            .select("location_id, duration_minutes, locations(location_name)")
            .eq("employee_id", employee_id)
            .execute()
        )
        visits = visits_resp.data or []

        sites_by_id = {}
        for v in visits:
            loc_id = v.get("location_id") or "unknown"
            loc_name = (v.get("locations") or {}).get("location_name") or "Unknown Site"
            entry = sites_by_id.setdefault(
                loc_id,
                {"location_name": loc_name, "visit_count": 0, "total_minutes": 0},
            )
            entry["visit_count"] += 1
            # Still-open visits (no departure yet) have duration_minutes =
            # null — counted as a visit, contributes 0 minutes until closed.
            entry["total_minutes"] += v.get("duration_minutes") or 0

        sites_worked = sorted(sites_by_id.values(), key=lambda s: -s["total_minutes"])

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
# SINGLE EMPLOYEE — MONTHLY ATTENDANCE
# =========================
# One employee, one calendar month: every day's record plus the month's
# totals (working hours, break time, overtime, lates) — for the
# "download this employee's monthly attendance" action.


def employee_monthly_attendance_report(employee_id: str, month: str):

    try:

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

        emp_resp = supabase_admin.table("employees").select("""
                full_name, employee_id,
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

        data = {
            "employee": employee,
            "month": month,
            "from_date": start.isoformat(),
            "to_date": end.isoformat(),
            "records": rows,
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
