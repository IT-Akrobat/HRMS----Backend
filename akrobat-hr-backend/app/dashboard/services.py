# # # from datetime import date, timedelta

# # # from fastapi import HTTPException

# # # from app.core.database import supabase_admin


# # # def get_admin_dashboard():

# # #     try:

# # #         today = str(date.today())

# # #         employees = supabase_admin.table("employees").select("id").execute()

# # #         attendance = (
# # #             supabase_admin.table("attendance")
# # #             .select("id")
# # #             .eq("attendance_date", today)
# # #             .execute()
# # #         )

# # #         # NOTE: previously filtered on a "leave_date" column on a "leaves"
# # #         # table — neither exists. The real table is "leave_requests" (see
# # #         # app/leaves/services.py), leaves are ranges (start_date/end_date),
# # #         # and status is a capitalised "Approved". So on_leave was always 0
# # #         # (or a hard 500, depending on which bug fired). Fixed to check "is
# # #         # this leave's range covering today" against the real table.
# # #         leaves = (
# # #             supabase_admin.table("leave_requests")
# # #             .select("id")
# # #             .eq("status", "Approved")
# # #             .lte("start_date", today)
# # #             .gte("end_date", today)
# # #             .execute()
# # #         )

# # #         departments = supabase_admin.table("departments").select("id").execute()

# # #         locations = supabase_admin.table("locations").select("id").execute()

# # #         shifts = supabase_admin.table("shifts").select("id").execute()

# # #         late = (
# # #             supabase_admin.table("attendance")
# # #             .select("id")
# # #             .eq("attendance_date", today)
# # #             .gt("late_minutes", 0)
# # #             .execute()
# # #         )

# # #         total_employees = len(employees.data)

# # #         present_today = len(attendance.data)

# # #         on_leave = len(leaves.data)

# # #         total_departments = len(departments.data)

# # #         total_locations = len(locations.data)

# # #         total_shifts = len(shifts.data)

# # #         late_today = len(late.data)

# # #         absent_today = max(0, total_employees - present_today - on_leave)

# # #         return {
# # #             "total_employees": total_employees,
# # #             "present_today": present_today,
# # #             "absent_today": absent_today,
# # #             "on_leave": on_leave,
# # #             "late_today": late_today,
# # #             "total_departments": total_departments,
# # #             "total_locations": total_locations,
# # #             "total_shifts": total_shifts,
# # #         }

# # #     except Exception as e:

# # #         raise HTTPException(status_code=500, detail=str(e))


# # # def get_attendance_trend(days: int = 7):
# # #     """Present / late / on-leave / absent counts per day, for the last
# # #     `days` days (inclusive of today) — feeds the dashboard trend chart.
# # #     Bucketed in Python from two range queries rather than one query per
# # #     day, so this stays cheap regardless of how many days are requested.
# # #     """

# # #     try:

# # #         end = date.today()

# # #         start = end - timedelta(days=days - 1)

# # #         total_employees = len(
# # #             supabase_admin.table("employees").select("id").execute().data or []
# # #         )

# # #         attendance_rows = (
# # #             supabase_admin.table("attendance")
# # #             .select("attendance_date, late_minutes")
# # #             .gte("attendance_date", start.isoformat())
# # #             .lte("attendance_date", end.isoformat())
# # #             .execute()
# # #             .data
# # #             or []
# # #         )

# # #         # A leave counts for a given day if that day falls inside its
# # #         # start_date/end_date range — same table/fix as get_admin_dashboard
# # #         # above (real table is "leave_requests", not "leaves").
# # #         leave_rows = (
# # #             supabase_admin.table("leave_requests")
# # #             .select("start_date, end_date")
# # #             .eq("status", "Approved")
# # #             .lte("start_date", end.isoformat())
# # #             .gte("end_date", start.isoformat())
# # #             .execute()
# # #             .data
# # #             or []
# # #         )

# # #         buckets = {}
# # #         cursor = start
# # #         while cursor <= end:
# # #             buckets[cursor.isoformat()] = {
# # #                 "date": cursor.isoformat(),
# # #                 "present": 0,
# # #                 "late": 0,
# # #                 "on_leave": 0,
# # #                 "absent": 0,
# # #             }
# # #             cursor += timedelta(days=1)

# # #         for row in attendance_rows:
# # #             bucket = buckets.get(row.get("attendance_date"))
# # #             if not bucket:
# # #                 continue
# # #             bucket["present"] += 1
# # #             if (row.get("late_minutes") or 0) > 0:
# # #                 bucket["late"] += 1

# # #         for row in leave_rows:
# # #             row_start = row.get("start_date")
# # #             row_end = row.get("end_date")
# # #             if not row_start or not row_end:
# # #                 continue
# # #             cursor = max(date.fromisoformat(row_start), start)
# # #             last = min(date.fromisoformat(row_end), end)
# # #             while cursor <= last:
# # #                 bucket = buckets.get(cursor.isoformat())
# # #                 if bucket:
# # #                     bucket["on_leave"] += 1
# # #                 cursor += timedelta(days=1)

# # #         trend = list(buckets.values())
# # #         for bucket in trend:
# # #             bucket["absent"] = max(
# # #                 0, total_employees - bucket["present"] - bucket["on_leave"]
# # #             )

# # #         return {"days": days, "total_employees": total_employees, "trend": trend}

# # #     except Exception as e:

# # #         raise HTTPException(status_code=500, detail=str(e))


# # # def get_department_distribution():
# # #     """Employee count per department — feeds the dashboard donut chart."""

# # #     try:

# # #         departments = (
# # #             supabase_admin.table("departments")
# # #             .select("id, department_name")
# # #             .execute()
# # #             .data
# # #             or []
# # #         )

# # #         employees = (
# # #             supabase_admin.table("employees").select("department_id").execute().data
# # #             or []
# # #         )

# # #         counts = {}
# # #         for row in employees:
# # #             dept_id = row.get("department_id")
# # #             counts[dept_id] = counts.get(dept_id, 0) + 1

# # #         result = [
# # #             {
# # #                 "department_id": dept["id"],
# # #                 "department_name": dept["department_name"],
# # #                 "employee_count": counts.get(dept["id"], 0),
# # #             }
# # #             for dept in departments
# # #         ]

# # #         unassigned = counts.get(None, 0)
# # #         if unassigned:
# # #             result.append(
# # #                 {
# # #                     "department_id": None,
# # #                     "department_name": "Unassigned",
# # #                     "employee_count": unassigned,
# # #                 }
# # #             )

# # #         result.sort(key=lambda d: d["employee_count"], reverse=True)

# # #         return {"departments": result}

# # #     except Exception as e:

# # #         raise HTTPException(status_code=500, detail=str(e))
# # from datetime import date, timedelta

# # from fastapi import HTTPException

# # from app.core.database import supabase_admin


# # def get_admin_dashboard():

# #     try:

# #         today = str(date.today())

# #         employees = supabase_admin.table("employees").select("id").execute()

# #         attendance = (
# #             supabase_admin.table("attendance")
# #             .select("id")
# #             .eq("attendance_date", today)
# #             .execute()
# #         )

# #         # NOTE: previously filtered on a "leave_date" column on a "leaves"
# #         # table — neither exists. The real table is "leave_requests" (see
# #         # app/leaves/services.py), leaves are ranges (start_date/end_date),
# #         # and status is a capitalised "Approved". So on_leave was always 0
# #         # (or a hard 500, depending on which bug fired). Fixed to check "is
# #         # this leave's range covering today" against the real table.
# #         leaves = (
# #             supabase_admin.table("leave_requests")
# #             .select("id")
# #             .eq("status", "Approved")
# #             .lte("start_date", today)
# #             .gte("end_date", today)
# #             .execute()
# #         )

# #         departments = supabase_admin.table("departments").select("id").execute()

# #         locations = supabase_admin.table("locations").select("id").execute()

# #         shifts = supabase_admin.table("shifts").select("id").execute()

# #         late = (
# #             supabase_admin.table("attendance")
# #             .select("id")
# #             .eq("attendance_date", today)
# #             .gt("late_minutes", 0)
# #             .execute()
# #         )

# #         total_employees = len(employees.data)

# #         present_today = len(attendance.data)

# #         on_leave = len(leaves.data)

# #         total_departments = len(departments.data)

# #         total_locations = len(locations.data)

# #         total_shifts = len(shifts.data)

# #         late_today = len(late.data)

# #         absent_today = max(0, total_employees - present_today - on_leave)

# #         return {
# #             "total_employees": total_employees,
# #             "present_today": present_today,
# #             "absent_today": absent_today,
# #             "on_leave": on_leave,
# #             "late_today": late_today,
# #             "total_departments": total_departments,
# #             "total_locations": total_locations,
# #             "total_shifts": total_shifts,
# #         }

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))


# # def get_attendance_trend(days: int = 7):
# #     """Present / late / on-leave / absent counts per day, for the last
# #     `days` days (inclusive of today) — feeds the dashboard trend chart.
# #     Bucketed in Python from two range queries rather than one query per
# #     day, so this stays cheap regardless of how many days are requested.
# #     """

# #     try:

# #         end = date.today()

# #         start = end - timedelta(days=days - 1)

# #         total_employees = len(
# #             supabase_admin.table("employees").select("id").execute().data or []
# #         )

# #         attendance_rows = (
# #             supabase_admin.table("attendance")
# #             .select("attendance_date, late_minutes")
# #             .gte("attendance_date", start.isoformat())
# #             .lte("attendance_date", end.isoformat())
# #             .execute()
# #             .data
# #             or []
# #         )

# #         # A leave counts for a given day if that day falls inside its
# #         # start_date/end_date range — same table/fix as get_admin_dashboard
# #         # above (real table is "leave_requests", not "leaves").
# #         leave_rows = (
# #             supabase_admin.table("leave_requests")
# #             .select("start_date, end_date")
# #             .eq("status", "Approved")
# #             .lte("start_date", end.isoformat())
# #             .gte("end_date", start.isoformat())
# #             .execute()
# #             .data
# #             or []
# #         )

# #         buckets = {}
# #         cursor = start
# #         while cursor <= end:
# #             buckets[cursor.isoformat()] = {
# #                 "date": cursor.isoformat(),
# #                 "present": 0,
# #                 "late": 0,
# #                 "on_leave": 0,
# #                 "absent": 0,
# #             }
# #             cursor += timedelta(days=1)

# #         for row in attendance_rows:
# #             bucket = buckets.get(row.get("attendance_date"))
# #             if not bucket:
# #                 continue
# #             bucket["present"] += 1
# #             if (row.get("late_minutes") or 0) > 0:
# #                 bucket["late"] += 1

# #         for row in leave_rows:
# #             row_start = row.get("start_date")
# #             row_end = row.get("end_date")
# #             if not row_start or not row_end:
# #                 continue
# #             cursor = max(date.fromisoformat(row_start), start)
# #             last = min(date.fromisoformat(row_end), end)
# #             while cursor <= last:
# #                 bucket = buckets.get(cursor.isoformat())
# #                 if bucket:
# #                     bucket["on_leave"] += 1
# #                 cursor += timedelta(days=1)

# #         trend = list(buckets.values())
# #         for bucket in trend:
# #             bucket["absent"] = max(
# #                 0, total_employees - bucket["present"] - bucket["on_leave"]
# #             )

# #         return {"days": days, "total_employees": total_employees, "trend": trend}

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))


# # def get_celebrations(days: int = 30):
# #     """Upcoming birthdays (employees.date_of_birth) and work
# #     anniversaries (employees.joining_date) within the next `days` days,
# #     company-wide — every employee, not scoped to a team, since this is
# #     a shared "who's celebrating soon" dashboard widget rather than a
# #     management view (no VIEW_EMPLOYEE-style permission gate on the
# #     route; see app/dashboard/routes.py).

# #     Year is ignored on both dates — only month+day matters — and the
# #     "next occurrence" is computed by rolling the month/day onto this
# #     year, then next year if that's already passed. Employees missing
# #     the relevant date (both are nullable — see sql/012_*.sql) are
# #     skipped rather than raising.
# #     """

# #     try:
# #         today = date.today()

# #         employees = (
# #             supabase_admin.table("employees")
# #             .select(
# #                 "id, employee_id, full_name, profile_photo, "
# #                 "date_of_birth, joining_date, employment_status"
# #             )
# #             .eq("employment_status", "Active")
# #             .execute()
# #             .data
# #             or []
# #         )

# #         def next_occurrence(iso_date_str):
# #             d = date.fromisoformat(iso_date_str)
# #             try:
# #                 this_year = d.replace(year=today.year)
# #             except ValueError:
# #                 # Feb 29 on a non-leap current year — observe on Mar 1.
# #                 this_year = date(today.year, 3, 1)
# #             if this_year < today:
# #                 try:
# #                     this_year = d.replace(year=today.year + 1)
# #                 except ValueError:
# #                     this_year = date(today.year + 1, 3, 1)
# #             return this_year

# #         birthdays = []
# #         anniversaries = []

# #         for emp in employees:
# #             base = {
# #                 "employee_id": emp["id"],
# #                 "employee_code": emp.get("employee_id"),
# #                 "full_name": emp.get("full_name"),
# #                 "profile_photo": emp.get("profile_photo"),
# #             }

# #             dob = emp.get("date_of_birth")
# #             if dob:
# #                 occurs_on = next_occurrence(dob)
# #                 days_away = (occurs_on - today).days
# #                 if 0 <= days_away <= days:
# #                     birthdays.append(
# #                         {
# #                             **base,
# #                             "date": occurs_on.isoformat(),
# #                             "days_away": days_away,
# #                         }
# #                     )

# #             joined = emp.get("joining_date")
# #             if joined:
# #                 occurs_on = next_occurrence(joined)
# #                 days_away = (occurs_on - today).days
# #                 years = occurs_on.year - date.fromisoformat(joined).year
# #                 if 0 <= days_away <= days and years > 0:
# #                     anniversaries.append(
# #                         {
# #                             **base,
# #                             "date": occurs_on.isoformat(),
# #                             "days_away": days_away,
# #                             "years": years,
# #                         }
# #                     )

# #         birthdays.sort(key=lambda r: r["days_away"])
# #         anniversaries.sort(key=lambda r: r["days_away"])

# #         return {
# #             "days": days,
# #             "birthdays": birthdays,
# #             "anniversaries": anniversaries,
# #         }

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))


# # def get_department_distribution():
# #     """Employee count per department — feeds the dashboard donut chart."""

# #     try:

# #         departments = (
# #             supabase_admin.table("departments")
# #             .select("id, department_name")
# #             .execute()
# #             .data
# #             or []
# #         )

# #         employees = (
# #             supabase_admin.table("employees").select("department_id").execute().data
# #             or []
# #         )

# #         counts = {}
# #         for row in employees:
# #             dept_id = row.get("department_id")
# #             counts[dept_id] = counts.get(dept_id, 0) + 1

# #         result = [
# #             {
# #                 "department_id": dept["id"],
# #                 "department_name": dept["department_name"],
# #                 "employee_count": counts.get(dept["id"], 0),
# #             }
# #             for dept in departments
# #         ]

# #         unassigned = counts.get(None, 0)
# #         if unassigned:
# #             result.append(
# #                 {
# #                     "department_id": None,
# #                     "department_name": "Unassigned",
# #                     "employee_count": unassigned,
# #                 }
# #             )

# #         result.sort(key=lambda d: d["employee_count"], reverse=True)

# #         return {"departments": result}

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))
# from datetime import date, timedelta

# from fastapi import HTTPException

# from app.core.database import supabase_admin


# def get_admin_dashboard():

#     try:

#         today = str(date.today())

#         employees = supabase_admin.table("employees").select("id").execute()

#         attendance = (
#             supabase_admin.table("attendance")
#             .select("id")
#             .eq("attendance_date", today)
#             .execute()
#         )

#         # NOTE: previously filtered on a "leave_date" column on a "leaves"
#         # table — neither exists. The real table is "leave_requests" (see
#         # app/leaves/services.py), leaves are ranges (start_date/end_date),
#         # and status is a capitalised "Approved". So on_leave was always 0
#         # (or a hard 500, depending on which bug fired). Fixed to check "is
#         # this leave's range covering today" against the real table.
#         leaves = (
#             supabase_admin.table("leave_requests")
#             .select("id")
#             .eq("status", "Approved")
#             .lte("start_date", today)
#             .gte("end_date", today)
#             .execute()
#         )

#         departments = supabase_admin.table("departments").select("id").execute()

#         locations = supabase_admin.table("locations").select("id").execute()

#         shifts = supabase_admin.table("shifts").select("id").execute()

#         late = (
#             supabase_admin.table("attendance")
#             .select("id")
#             .eq("attendance_date", today)
#             .gt("late_minutes", 0)
#             .execute()
#         )

#         total_employees = len(employees.data)

#         present_today = len(attendance.data)

#         on_leave = len(leaves.data)

#         total_departments = len(departments.data)

#         total_locations = len(locations.data)

#         total_shifts = len(shifts.data)

#         late_today = len(late.data)

#         absent_today = max(0, total_employees - present_today - on_leave)

#         return {
#             "total_employees": total_employees,
#             "present_today": present_today,
#             "absent_today": absent_today,
#             "on_leave": on_leave,
#             "late_today": late_today,
#             "total_departments": total_departments,
#             "total_locations": total_locations,
#             "total_shifts": total_shifts,
#         }

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_attendance_trend(days: int = 7):
#     """Present / late / on-leave / absent counts per day, for the last
#     `days` days (inclusive of today) — feeds the dashboard trend chart.
#     Bucketed in Python from two range queries rather than one query per
#     day, so this stays cheap regardless of how many days are requested.
#     """

#     try:

#         end = date.today()

#         start = end - timedelta(days=days - 1)

#         total_employees = len(
#             supabase_admin.table("employees").select("id").execute().data or []
#         )

#         attendance_rows = (
#             supabase_admin.table("attendance")
#             .select("attendance_date, late_minutes")
#             .gte("attendance_date", start.isoformat())
#             .lte("attendance_date", end.isoformat())
#             .execute()
#             .data
#             or []
#         )

#         # A leave counts for a given day if that day falls inside its
#         # start_date/end_date range — same table/fix as get_admin_dashboard
#         # above (real table is "leave_requests", not "leaves").
#         leave_rows = (
#             supabase_admin.table("leave_requests")
#             .select("start_date, end_date")
#             .eq("status", "Approved")
#             .lte("start_date", end.isoformat())
#             .gte("end_date", start.isoformat())
#             .execute()
#             .data
#             or []
#         )

#         buckets = {}
#         cursor = start
#         while cursor <= end:
#             buckets[cursor.isoformat()] = {
#                 "date": cursor.isoformat(),
#                 "present": 0,
#                 "late": 0,
#                 "on_leave": 0,
#                 "absent": 0,
#             }
#             cursor += timedelta(days=1)

#         for row in attendance_rows:
#             bucket = buckets.get(row.get("attendance_date"))
#             if not bucket:
#                 continue
#             bucket["present"] += 1
#             if (row.get("late_minutes") or 0) > 0:
#                 bucket["late"] += 1

#         for row in leave_rows:
#             row_start = row.get("start_date")
#             row_end = row.get("end_date")
#             if not row_start or not row_end:
#                 continue
#             cursor = max(date.fromisoformat(row_start), start)
#             last = min(date.fromisoformat(row_end), end)
#             while cursor <= last:
#                 bucket = buckets.get(cursor.isoformat())
#                 if bucket:
#                     bucket["on_leave"] += 1
#                 cursor += timedelta(days=1)

#         trend = list(buckets.values())
#         for bucket in trend:
#             bucket["absent"] = max(
#                 0, total_employees - bucket["present"] - bucket["on_leave"]
#             )

#         return {"days": days, "total_employees": total_employees, "trend": trend}

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_celebrations(days: int = 30):
#     """Upcoming birthdays (employees.date_of_birth) and work
#     anniversaries (employees.joining_date) within the next `days` days,
#     company-wide — every employee, not scoped to a team, since this is
#     a shared "who's celebrating soon" dashboard widget rather than a
#     management view (no VIEW_EMPLOYEE-style permission gate on the
#     route; see app/dashboard/routes.py).

#     Year is ignored on both dates — only month+day matters — and the
#     "next occurrence" is computed by rolling the month/day onto this
#     year, then next year if that's already passed. Employees missing
#     the relevant date (both are nullable — see sql/012_*.sql) are
#     skipped rather than raising.
#     """

#     try:
#         today = date.today()

#         employees = (
#             supabase_admin.table("employees")
#             .select(
#                 "id, employee_id, full_name, profile_photo, "
#                 "date_of_birth, joining_date, employment_status"
#             )
#             .eq("employment_status", "Active")
#             .execute()
#             .data
#             or []
#         )

#         def next_occurrence(iso_date_str):
#             d = date.fromisoformat(iso_date_str)
#             try:
#                 this_year = d.replace(year=today.year)
#             except ValueError:
#                 # Feb 29 on a non-leap current year — observe on Mar 1.
#                 this_year = date(today.year, 3, 1)
#             if this_year < today:
#                 try:
#                     this_year = d.replace(year=today.year + 1)
#                 except ValueError:
#                     this_year = date(today.year + 1, 3, 1)
#             return this_year

#         birthdays = []
#         anniversaries = []

#         for emp in employees:
#             base = {
#                 "employee_id": emp["id"],
#                 "employee_code": emp.get("employee_id"),
#                 "full_name": emp.get("full_name"),
#                 "profile_photo": emp.get("profile_photo"),
#             }

#             dob = emp.get("date_of_birth")
#             if dob:
#                 occurs_on = next_occurrence(dob)
#                 days_away = (occurs_on - today).days
#                 if 0 <= days_away <= days:
#                     birthdays.append(
#                         {
#                             **base,
#                             "date": occurs_on.isoformat(),
#                             "days_away": days_away,
#                         }
#                     )

#             joined = emp.get("joining_date")
#             if joined:
#                 occurs_on = next_occurrence(joined)
#                 days_away = (occurs_on - today).days
#                 years = occurs_on.year - date.fromisoformat(joined).year
#                 if 0 <= days_away <= days and years > 0:
#                     anniversaries.append(
#                         {
#                             **base,
#                             "date": occurs_on.isoformat(),
#                             "days_away": days_away,
#                             "years": years,
#                         }
#                     )

#         birthdays.sort(key=lambda r: r["days_away"])
#         anniversaries.sort(key=lambda r: r["days_away"])

#         return {
#             "days": days,
#             "birthdays": birthdays,
#             "anniversaries": anniversaries,
#         }

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_on_leave_today():
#     """Employees whose *approved* leave covers today's date, company-wide.

#     Same rationale as get_celebrations() above: this is a shared dashboard
#     widget (not an employee-management view), so no VIEW_EMPLOYEE-style
#     permission gate on the route — see app/dashboard/routes.py.

#     Filters leave_requests where status = 'Approved' and
#     start_date <= today <= end_date, joining employees for name/photo/
#     department and leave_types for the leave label.
#     """

#     try:
#         today = date.today().isoformat()

#         response = (
#             supabase_admin.table("leave_requests")
#             .select(
#                 "id, start_date, end_date, total_days, "
#                 "employees!leave_requests_employee_id_fkey("
#                 "id, full_name, employee_id, profile_photo, "
#                 "departments!employees_department_id_fkey(department_name)"
#                 "), "
#                 "leave_types(leave_name)"
#             )
#             .eq("status", "Approved")
#             .lte("start_date", today)
#             .gte("end_date", today)
#             .execute()
#         )

#         records = response.data or []

#         results = []
#         for row in records:
#             emp = row.get("employees") or {}
#             leave_type = row.get("leave_types") or {}
#             results.append(
#                 {
#                     "employee_id": emp.get("id"),
#                     "employee_code": emp.get("employee_id"),
#                     "full_name": emp.get("full_name"),
#                     "profile_photo": emp.get("profile_photo"),
#                     "department_name": (emp.get("departments") or {}).get(
#                         "department_name"
#                     ),
#                     "leave_type": leave_type.get("leave_name"),
#                     "start_date": row.get("start_date"),
#                     "end_date": row.get("end_date"),
#                     "total_days": row.get("total_days"),
#                 }
#             )

#         results.sort(key=lambda r: r["full_name"] or "")

#         return {"date": today, "count": len(results), "employees": results}

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_department_distribution():
#     """Employee count per department — feeds the dashboard donut chart."""

#     try:

#         departments = (
#             supabase_admin.table("departments")
#             .select("id, department_name")
#             .execute()
#             .data
#             or []
#         )

#         employees = (
#             supabase_admin.table("employees").select("department_id").execute().data
#             or []
#         )

#         counts = {}
#         for row in employees:
#             dept_id = row.get("department_id")
#             counts[dept_id] = counts.get(dept_id, 0) + 1

#         result = [
#             {
#                 "department_id": dept["id"],
#                 "department_name": dept["department_name"],
#                 "employee_count": counts.get(dept["id"], 0),
#             }
#             for dept in departments
#         ]

#         unassigned = counts.get(None, 0)
#         if unassigned:
#             result.append(
#                 {
#                     "department_id": None,
#                     "department_name": "Unassigned",
#                     "employee_count": unassigned,
#                 }
#             )

#         result.sort(key=lambda d: d["employee_count"], reverse=True)

#         return {"departments": result}

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# # from datetime import date, timedelta

# # from fastapi import HTTPException

# # from app.core.database import supabase_admin


# # def get_admin_dashboard():

# #     try:

# #         today = str(date.today())

# #         employees = supabase_admin.table("employees").select("id").execute()

# #         attendance = (
# #             supabase_admin.table("attendance")
# #             .select("id")
# #             .eq("attendance_date", today)
# #             .execute()
# #         )

# #         # NOTE: previously filtered on a "leave_date" column on a "leaves"
# #         # table — neither exists. The real table is "leave_requests" (see
# #         # app/leaves/services.py), leaves are ranges (start_date/end_date),
# #         # and status is a capitalised "Approved". So on_leave was always 0
# #         # (or a hard 500, depending on which bug fired). Fixed to check "is
# #         # this leave's range covering today" against the real table.
# #         leaves = (
# #             supabase_admin.table("leave_requests")
# #             .select("id")
# #             .eq("status", "Approved")
# #             .lte("start_date", today)
# #             .gte("end_date", today)
# #             .execute()
# #         )

# #         departments = supabase_admin.table("departments").select("id").execute()

# #         locations = supabase_admin.table("locations").select("id").execute()

# #         shifts = supabase_admin.table("shifts").select("id").execute()

# #         late = (
# #             supabase_admin.table("attendance")
# #             .select("id")
# #             .eq("attendance_date", today)
# #             .gt("late_minutes", 0)
# #             .execute()
# #         )

# #         total_employees = len(employees.data)

# #         present_today = len(attendance.data)

# #         on_leave = len(leaves.data)

# #         total_departments = len(departments.data)

# #         total_locations = len(locations.data)

# #         total_shifts = len(shifts.data)

# #         late_today = len(late.data)

# #         absent_today = max(0, total_employees - present_today - on_leave)

# #         return {
# #             "total_employees": total_employees,
# #             "present_today": present_today,
# #             "absent_today": absent_today,
# #             "on_leave": on_leave,
# #             "late_today": late_today,
# #             "total_departments": total_departments,
# #             "total_locations": total_locations,
# #             "total_shifts": total_shifts,
# #         }

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))


# # def get_attendance_trend(days: int = 7):
# #     """Present / late / on-leave / absent counts per day, for the last
# #     `days` days (inclusive of today) — feeds the dashboard trend chart.
# #     Bucketed in Python from two range queries rather than one query per
# #     day, so this stays cheap regardless of how many days are requested.
# #     """

# #     try:

# #         end = date.today()

# #         start = end - timedelta(days=days - 1)

# #         total_employees = len(
# #             supabase_admin.table("employees").select("id").execute().data or []
# #         )

# #         attendance_rows = (
# #             supabase_admin.table("attendance")
# #             .select("attendance_date, late_minutes")
# #             .gte("attendance_date", start.isoformat())
# #             .lte("attendance_date", end.isoformat())
# #             .execute()
# #             .data
# #             or []
# #         )

# #         # A leave counts for a given day if that day falls inside its
# #         # start_date/end_date range — same table/fix as get_admin_dashboard
# #         # above (real table is "leave_requests", not "leaves").
# #         leave_rows = (
# #             supabase_admin.table("leave_requests")
# #             .select("start_date, end_date")
# #             .eq("status", "Approved")
# #             .lte("start_date", end.isoformat())
# #             .gte("end_date", start.isoformat())
# #             .execute()
# #             .data
# #             or []
# #         )

# #         buckets = {}
# #         cursor = start
# #         while cursor <= end:
# #             buckets[cursor.isoformat()] = {
# #                 "date": cursor.isoformat(),
# #                 "present": 0,
# #                 "late": 0,
# #                 "on_leave": 0,
# #                 "absent": 0,
# #             }
# #             cursor += timedelta(days=1)

# #         for row in attendance_rows:
# #             bucket = buckets.get(row.get("attendance_date"))
# #             if not bucket:
# #                 continue
# #             bucket["present"] += 1
# #             if (row.get("late_minutes") or 0) > 0:
# #                 bucket["late"] += 1

# #         for row in leave_rows:
# #             row_start = row.get("start_date")
# #             row_end = row.get("end_date")
# #             if not row_start or not row_end:
# #                 continue
# #             cursor = max(date.fromisoformat(row_start), start)
# #             last = min(date.fromisoformat(row_end), end)
# #             while cursor <= last:
# #                 bucket = buckets.get(cursor.isoformat())
# #                 if bucket:
# #                     bucket["on_leave"] += 1
# #                 cursor += timedelta(days=1)

# #         trend = list(buckets.values())
# #         for bucket in trend:
# #             bucket["absent"] = max(
# #                 0, total_employees - bucket["present"] - bucket["on_leave"]
# #             )

# #         return {"days": days, "total_employees": total_employees, "trend": trend}

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))


# # def get_department_distribution():
# #     """Employee count per department — feeds the dashboard donut chart."""

# #     try:

# #         departments = (
# #             supabase_admin.table("departments")
# #             .select("id, department_name")
# #             .execute()
# #             .data
# #             or []
# #         )

# #         employees = (
# #             supabase_admin.table("employees").select("department_id").execute().data
# #             or []
# #         )

# #         counts = {}
# #         for row in employees:
# #             dept_id = row.get("department_id")
# #             counts[dept_id] = counts.get(dept_id, 0) + 1

# #         result = [
# #             {
# #                 "department_id": dept["id"],
# #                 "department_name": dept["department_name"],
# #                 "employee_count": counts.get(dept["id"], 0),
# #             }
# #             for dept in departments
# #         ]

# #         unassigned = counts.get(None, 0)
# #         if unassigned:
# #             result.append(
# #                 {
# #                     "department_id": None,
# #                     "department_name": "Unassigned",
# #                     "employee_count": unassigned,
# #                 }
# #             )

# #         result.sort(key=lambda d: d["employee_count"], reverse=True)

# #         return {"departments": result}

# #     except Exception as e:

# #         raise HTTPException(status_code=500, detail=str(e))
# from datetime import date, timedelta

# from fastapi import HTTPException

# from app.core.database import supabase_admin


# def get_admin_dashboard():

#     try:

#         today = str(date.today())

#         employees = supabase_admin.table("employees").select("id").execute()

#         attendance = (
#             supabase_admin.table("attendance")
#             .select("id")
#             .eq("attendance_date", today)
#             .execute()
#         )

#         # NOTE: previously filtered on a "leave_date" column on a "leaves"
#         # table — neither exists. The real table is "leave_requests" (see
#         # app/leaves/services.py), leaves are ranges (start_date/end_date),
#         # and status is a capitalised "Approved". So on_leave was always 0
#         # (or a hard 500, depending on which bug fired). Fixed to check "is
#         # this leave's range covering today" against the real table.
#         leaves = (
#             supabase_admin.table("leave_requests")
#             .select("id")
#             .eq("status", "Approved")
#             .lte("start_date", today)
#             .gte("end_date", today)
#             .execute()
#         )

#         departments = supabase_admin.table("departments").select("id").execute()

#         locations = supabase_admin.table("locations").select("id").execute()

#         shifts = supabase_admin.table("shifts").select("id").execute()

#         late = (
#             supabase_admin.table("attendance")
#             .select("id")
#             .eq("attendance_date", today)
#             .gt("late_minutes", 0)
#             .execute()
#         )

#         total_employees = len(employees.data)

#         present_today = len(attendance.data)

#         on_leave = len(leaves.data)

#         total_departments = len(departments.data)

#         total_locations = len(locations.data)

#         total_shifts = len(shifts.data)

#         late_today = len(late.data)

#         absent_today = max(0, total_employees - present_today - on_leave)

#         return {
#             "total_employees": total_employees,
#             "present_today": present_today,
#             "absent_today": absent_today,
#             "on_leave": on_leave,
#             "late_today": late_today,
#             "total_departments": total_departments,
#             "total_locations": total_locations,
#             "total_shifts": total_shifts,
#         }

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_attendance_trend(days: int = 7):
#     """Present / late / on-leave / absent counts per day, for the last
#     `days` days (inclusive of today) — feeds the dashboard trend chart.
#     Bucketed in Python from two range queries rather than one query per
#     day, so this stays cheap regardless of how many days are requested.
#     """

#     try:

#         end = date.today()

#         start = end - timedelta(days=days - 1)

#         total_employees = len(
#             supabase_admin.table("employees").select("id").execute().data or []
#         )

#         attendance_rows = (
#             supabase_admin.table("attendance")
#             .select("attendance_date, late_minutes")
#             .gte("attendance_date", start.isoformat())
#             .lte("attendance_date", end.isoformat())
#             .execute()
#             .data
#             or []
#         )

#         # A leave counts for a given day if that day falls inside its
#         # start_date/end_date range — same table/fix as get_admin_dashboard
#         # above (real table is "leave_requests", not "leaves").
#         leave_rows = (
#             supabase_admin.table("leave_requests")
#             .select("start_date, end_date")
#             .eq("status", "Approved")
#             .lte("start_date", end.isoformat())
#             .gte("end_date", start.isoformat())
#             .execute()
#             .data
#             or []
#         )

#         buckets = {}
#         cursor = start
#         while cursor <= end:
#             buckets[cursor.isoformat()] = {
#                 "date": cursor.isoformat(),
#                 "present": 0,
#                 "late": 0,
#                 "on_leave": 0,
#                 "absent": 0,
#             }
#             cursor += timedelta(days=1)

#         for row in attendance_rows:
#             bucket = buckets.get(row.get("attendance_date"))
#             if not bucket:
#                 continue
#             bucket["present"] += 1
#             if (row.get("late_minutes") or 0) > 0:
#                 bucket["late"] += 1

#         for row in leave_rows:
#             row_start = row.get("start_date")
#             row_end = row.get("end_date")
#             if not row_start or not row_end:
#                 continue
#             cursor = max(date.fromisoformat(row_start), start)
#             last = min(date.fromisoformat(row_end), end)
#             while cursor <= last:
#                 bucket = buckets.get(cursor.isoformat())
#                 if bucket:
#                     bucket["on_leave"] += 1
#                 cursor += timedelta(days=1)

#         trend = list(buckets.values())
#         for bucket in trend:
#             bucket["absent"] = max(
#                 0, total_employees - bucket["present"] - bucket["on_leave"]
#             )

#         return {"days": days, "total_employees": total_employees, "trend": trend}

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_celebrations(days: int = 30):
#     """Upcoming birthdays (employees.date_of_birth) and work
#     anniversaries (employees.joining_date) within the next `days` days,
#     company-wide — every employee, not scoped to a team, since this is
#     a shared "who's celebrating soon" dashboard widget rather than a
#     management view (no VIEW_EMPLOYEE-style permission gate on the
#     route; see app/dashboard/routes.py).

#     Year is ignored on both dates — only month+day matters — and the
#     "next occurrence" is computed by rolling the month/day onto this
#     year, then next year if that's already passed. Employees missing
#     the relevant date (both are nullable — see sql/012_*.sql) are
#     skipped rather than raising.
#     """

#     try:
#         today = date.today()

#         employees = (
#             supabase_admin.table("employees")
#             .select(
#                 "id, employee_id, full_name, profile_photo, "
#                 "date_of_birth, joining_date, employment_status"
#             )
#             .eq("employment_status", "Active")
#             .execute()
#             .data
#             or []
#         )

#         def next_occurrence(iso_date_str):
#             d = date.fromisoformat(iso_date_str)
#             try:
#                 this_year = d.replace(year=today.year)
#             except ValueError:
#                 # Feb 29 on a non-leap current year — observe on Mar 1.
#                 this_year = date(today.year, 3, 1)
#             if this_year < today:
#                 try:
#                     this_year = d.replace(year=today.year + 1)
#                 except ValueError:
#                     this_year = date(today.year + 1, 3, 1)
#             return this_year

#         birthdays = []
#         anniversaries = []

#         for emp in employees:
#             base = {
#                 "employee_id": emp["id"],
#                 "employee_code": emp.get("employee_id"),
#                 "full_name": emp.get("full_name"),
#                 "profile_photo": emp.get("profile_photo"),
#             }

#             dob = emp.get("date_of_birth")
#             if dob:
#                 occurs_on = next_occurrence(dob)
#                 days_away = (occurs_on - today).days
#                 if 0 <= days_away <= days:
#                     birthdays.append(
#                         {
#                             **base,
#                             "date": occurs_on.isoformat(),
#                             "days_away": days_away,
#                         }
#                     )

#             joined = emp.get("joining_date")
#             if joined:
#                 occurs_on = next_occurrence(joined)
#                 days_away = (occurs_on - today).days
#                 years = occurs_on.year - date.fromisoformat(joined).year
#                 if 0 <= days_away <= days and years > 0:
#                     anniversaries.append(
#                         {
#                             **base,
#                             "date": occurs_on.isoformat(),
#                             "days_away": days_away,
#                             "years": years,
#                         }
#                     )

#         birthdays.sort(key=lambda r: r["days_away"])
#         anniversaries.sort(key=lambda r: r["days_away"])

#         return {
#             "days": days,
#             "birthdays": birthdays,
#             "anniversaries": anniversaries,
#         }

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))


# def get_department_distribution():
#     """Employee count per department — feeds the dashboard donut chart."""

#     try:

#         departments = (
#             supabase_admin.table("departments")
#             .select("id, department_name")
#             .execute()
#             .data
#             or []
#         )

#         employees = (
#             supabase_admin.table("employees").select("department_id").execute().data
#             or []
#         )

#         counts = {}
#         for row in employees:
#             dept_id = row.get("department_id")
#             counts[dept_id] = counts.get(dept_id, 0) + 1

#         result = [
#             {
#                 "department_id": dept["id"],
#                 "department_name": dept["department_name"],
#                 "employee_count": counts.get(dept["id"], 0),
#             }
#             for dept in departments
#         ]

#         unassigned = counts.get(None, 0)
#         if unassigned:
#             result.append(
#                 {
#                     "department_id": None,
#                     "department_name": "Unassigned",
#                     "employee_count": unassigned,
#                 }
#             )

#         result.sort(key=lambda d: d["employee_count"], reverse=True)

#         return {"departments": result}

#     except Exception as e:

#         raise HTTPException(status_code=500, detail=str(e))
from datetime import date, timedelta

import random

import httpx

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.config import PEXELS_API_KEY, PEXELS_SEARCH_QUERY, QUOTE_API_URL
from app.core.logger import logger


def get_admin_dashboard():

    try:

        today = str(date.today())

        employees = supabase_admin.table("employees").select("id").execute()

        attendance = (
            supabase_admin.table("attendance")
            .select("id")
            .eq("attendance_date", today)
            .execute()
        )

        # NOTE: previously filtered on a "leave_date" column on a "leaves"
        # table — neither exists. The real table is "leave_requests" (see
        # app/leaves/services.py), leaves are ranges (start_date/end_date),
        # and status is a capitalised "Approved". So on_leave was always 0
        # (or a hard 500, depending on which bug fired). Fixed to check "is
        # this leave's range covering today" against the real table.
        leaves = (
            supabase_admin.table("leave_requests")
            .select("id")
            .eq("status", "Approved")
            .lte("start_date", today)
            .gte("end_date", today)
            .execute()
        )

        departments = supabase_admin.table("departments").select("id").execute()

        locations = supabase_admin.table("locations").select("id").execute()

        shifts = supabase_admin.table("shifts").select("id").execute()

        late = (
            supabase_admin.table("attendance")
            .select("id")
            .eq("attendance_date", today)
            .gt("late_minutes", 0)
            .execute()
        )

        total_employees = len(employees.data)

        present_today = len(attendance.data)

        on_leave = len(leaves.data)

        total_departments = len(departments.data)

        total_locations = len(locations.data)

        total_shifts = len(shifts.data)

        late_today = len(late.data)

        absent_today = max(0, total_employees - present_today - on_leave)

        return {
            "total_employees": total_employees,
            "present_today": present_today,
            "absent_today": absent_today,
            "on_leave": on_leave,
            "late_today": late_today,
            "total_departments": total_departments,
            "total_locations": total_locations,
            "total_shifts": total_shifts,
        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


def get_attendance_trend(days: int = 7):
    """Present / late / on-leave / absent counts per day, for the last
    `days` days (inclusive of today) — feeds the dashboard trend chart.
    Bucketed in Python from two range queries rather than one query per
    day, so this stays cheap regardless of how many days are requested.
    """

    try:

        end = date.today()

        start = end - timedelta(days=days - 1)

        total_employees = len(
            supabase_admin.table("employees").select("id").execute().data or []
        )

        attendance_rows = (
            supabase_admin.table("attendance")
            .select("attendance_date, late_minutes")
            .gte("attendance_date", start.isoformat())
            .lte("attendance_date", end.isoformat())
            .execute()
            .data
            or []
        )

        # A leave counts for a given day if that day falls inside its
        # start_date/end_date range — same table/fix as get_admin_dashboard
        # above (real table is "leave_requests", not "leaves").
        leave_rows = (
            supabase_admin.table("leave_requests")
            .select("start_date, end_date")
            .eq("status", "Approved")
            .lte("start_date", end.isoformat())
            .gte("end_date", start.isoformat())
            .execute()
            .data
            or []
        )

        buckets = {}
        cursor = start
        while cursor <= end:
            buckets[cursor.isoformat()] = {
                "date": cursor.isoformat(),
                "present": 0,
                "late": 0,
                "on_leave": 0,
                "absent": 0,
            }
            cursor += timedelta(days=1)

        for row in attendance_rows:
            bucket = buckets.get(row.get("attendance_date"))
            if not bucket:
                continue
            bucket["present"] += 1
            if (row.get("late_minutes") or 0) > 0:
                bucket["late"] += 1

        for row in leave_rows:
            row_start = row.get("start_date")
            row_end = row.get("end_date")
            if not row_start or not row_end:
                continue
            cursor = max(date.fromisoformat(row_start), start)
            last = min(date.fromisoformat(row_end), end)
            while cursor <= last:
                bucket = buckets.get(cursor.isoformat())
                if bucket:
                    bucket["on_leave"] += 1
                cursor += timedelta(days=1)

        trend = list(buckets.values())
        for bucket in trend:
            bucket["absent"] = max(
                0, total_employees - bucket["present"] - bucket["on_leave"]
            )

        return {"days": days, "total_employees": total_employees, "trend": trend}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


def get_celebrations(days: int = 30):
    """Upcoming birthdays (employees.date_of_birth) and work
    anniversaries (employees.joining_date) within the next `days` days,
    company-wide — every employee, not scoped to a team, since this is
    a shared "who's celebrating soon" dashboard widget rather than a
    management view (no VIEW_EMPLOYEE-style permission gate on the
    route; see app/dashboard/routes.py).

    Year is ignored on both dates — only month+day matters — and the
    "next occurrence" is computed by rolling the month/day onto this
    year, then next year if that's already passed. Employees missing
    the relevant date (both are nullable — see sql/012_*.sql) are
    skipped rather than raising.
    """

    try:
        today = date.today()

        employees = (
            supabase_admin.table("employees")
            .select(
                "id, employee_id, full_name, profile_photo, "
                "date_of_birth, joining_date, employment_status"
            )
            .eq("employment_status", "Active")
            .execute()
            .data
            or []
        )

        def next_occurrence(iso_date_str):
            d = date.fromisoformat(iso_date_str)
            try:
                this_year = d.replace(year=today.year)
            except ValueError:
                # Feb 29 on a non-leap current year — observe on Mar 1.
                this_year = date(today.year, 3, 1)
            if this_year < today:
                try:
                    this_year = d.replace(year=today.year + 1)
                except ValueError:
                    this_year = date(today.year + 1, 3, 1)
            return this_year

        birthdays = []
        anniversaries = []

        for emp in employees:
            base = {
                "employee_id": emp["id"],
                "employee_code": emp.get("employee_id"),
                "full_name": emp.get("full_name"),
                "profile_photo": emp.get("profile_photo"),
            }

            dob = emp.get("date_of_birth")
            if dob:
                occurs_on = next_occurrence(dob)
                days_away = (occurs_on - today).days
                if 0 <= days_away <= days:
                    birthdays.append(
                        {
                            **base,
                            "date": occurs_on.isoformat(),
                            "days_away": days_away,
                        }
                    )

            joined = emp.get("joining_date")
            if joined:
                occurs_on = next_occurrence(joined)
                days_away = (occurs_on - today).days
                years = occurs_on.year - date.fromisoformat(joined).year
                if 0 <= days_away <= days and years > 0:
                    anniversaries.append(
                        {
                            **base,
                            "date": occurs_on.isoformat(),
                            "days_away": days_away,
                            "years": years,
                        }
                    )

        birthdays.sort(key=lambda r: r["days_away"])
        anniversaries.sort(key=lambda r: r["days_away"])

        return {
            "days": days,
            "birthdays": birthdays,
            "anniversaries": anniversaries,
        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


def get_on_leave_today():
    """Employees whose *approved* leave covers today's date, company-wide.

    Same rationale as get_celebrations() above: this is a shared dashboard
    widget (not an employee-management view), so no VIEW_EMPLOYEE-style
    permission gate on the route — see app/dashboard/routes.py.

    Filters leave_requests where status = 'Approved' and
    start_date <= today <= end_date, joining employees for name/photo/
    department and leave_types for the leave label.
    """

    try:
        today = date.today().isoformat()

        response = (
            supabase_admin.table("leave_requests")
            .select(
                "id, start_date, end_date, total_days, "
                "employees!leave_requests_employee_id_fkey("
                "id, full_name, employee_id, profile_photo, "
                "departments!employees_department_id_fkey(department_name)"
                "), "
                "leave_types(leave_name)"
            )
            .eq("status", "Approved")
            .lte("start_date", today)
            .gte("end_date", today)
            .execute()
        )

        records = response.data or []

        results = []
        for row in records:
            emp = row.get("employees") or {}
            leave_type = row.get("leave_types") or {}
            results.append(
                {
                    "employee_id": emp.get("id"),
                    "employee_code": emp.get("employee_id"),
                    "full_name": emp.get("full_name"),
                    "profile_photo": emp.get("profile_photo"),
                    "department_name": (emp.get("departments") or {}).get(
                        "department_name"
                    ),
                    "leave_type": leave_type.get("leave_name"),
                    "start_date": row.get("start_date"),
                    "end_date": row.get("end_date"),
                    "total_days": row.get("total_days"),
                }
            )

        results.sort(key=lambda r: r["full_name"] or "")

        return {"date": today, "count": len(results), "employees": results}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


def get_department_distribution():
    """Employee count per department — feeds the dashboard donut chart."""

    try:

        departments = (
            supabase_admin.table("departments")
            .select("id, department_name")
            .execute()
            .data
            or []
        )

        employees = (
            supabase_admin.table("employees").select("department_id").execute().data
            or []
        )

        counts = {}
        for row in employees:
            dept_id = row.get("department_id")
            counts[dept_id] = counts.get(dept_id, 0) + 1

        result = [
            {
                "department_id": dept["id"],
                "department_name": dept["department_name"],
                "employee_count": counts.get(dept["id"], 0),
            }
            for dept in departments
        ]

        unassigned = counts.get(None, 0)
        if unassigned:
            result.append(
                {
                    "department_id": None,
                    "department_name": "Unassigned",
                    "employee_count": unassigned,
                }
            )

        result.sort(key=lambda d: d["employee_count"], reverse=True)

        return {"departments": result}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# Present days needed in the window before an employee is ranked at all —
# stops one lucky on-time day for a brand-new employee from outranking
# someone with weeks of consistent attendance.
TOP_PERFORMERS_MIN_PRESENT_DAYS = 3


def get_top_performers(days: int = 30, limit: int = 5):
    """Ranks employees by attendance reliability over the last `days`
    days: punctuality rate (share of present days with zero late_minutes)
    first, then days present, then overtime minutes as tiebreakers.

    There's no separate "performance rating" concept anywhere in this
    schema, so rather than invent one, this is derived entirely from the
    `attendance` table (see sql/001_schema.sql) — the same source of
    truth the attendance trend chart and audit-log activity use.
    """

    try:

        end = date.today()

        start = end - timedelta(days=days - 1)

        rows = (
            supabase_admin.table("attendance")
            .select("employee_id, late_minutes, working_minutes, overtime_minutes")
            .gte("attendance_date", start.isoformat())
            .lte("attendance_date", end.isoformat())
            .execute()
            .data
            or []
        )

        by_employee = {}
        for row in rows:
            emp_id = row.get("employee_id")
            if not emp_id:
                continue
            bucket = by_employee.setdefault(
                emp_id,
                {
                    "present_days": 0,
                    "on_time_days": 0,
                    "working_minutes": 0,
                    "overtime_minutes": 0,
                },
            )
            bucket["present_days"] += 1
            if (row.get("late_minutes") or 0) == 0:
                bucket["on_time_days"] += 1
            bucket["working_minutes"] += row.get("working_minutes") or 0
            bucket["overtime_minutes"] += row.get("overtime_minutes") or 0

        eligible = {
            emp_id: b
            for emp_id, b in by_employee.items()
            if b["present_days"] >= TOP_PERFORMERS_MIN_PRESENT_DAYS
        }

        if not eligible:
            return {"days": days, "employees": []}

        employees = (
            supabase_admin.table("employees")
            .select(
                "id, full_name, employee_id, profile_photo, "
                "departments!employees_department_id_fkey(department_name)"
            )
            .in_("id", list(eligible.keys()))
            .execute()
            .data
            or []
        )

        emp_by_id = {e["id"]: e for e in employees}

        results = []
        for emp_id, b in eligible.items():
            emp = emp_by_id.get(emp_id)
            if not emp:
                continue
            punctuality_rate = b["on_time_days"] / b["present_days"]
            results.append(
                {
                    "employee_id": emp_id,
                    "employee_code": emp.get("employee_id"),
                    "full_name": emp.get("full_name"),
                    "profile_photo": emp.get("profile_photo"),
                    "department_name": (emp.get("departments") or {}).get(
                        "department_name"
                    ),
                    "present_days": b["present_days"],
                    "on_time_days": b["on_time_days"],
                    "punctuality_rate": round(punctuality_rate * 100, 1),
                    "working_minutes": b["working_minutes"],
                    "overtime_minutes": b["overtime_minutes"],
                }
            )

        results.sort(
            key=lambda r: (
                r["punctuality_rate"],
                r["present_days"],
                r["overtime_minutes"],
            ),
            reverse=True,
        )

        return {"days": days, "employees": results[:limit]}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# QUOTE OF THE DAY
# =========================================================================
# GET /dashboard/quote-of-day (see app/dashboard/routes.py)
#
# One row per calendar day in `daily_quotes` (unique on quote_date — see
# sql/014_daily_quotes.sql) acts as the cache: whichever request is first
# to load the dashboard on a given day pays the cost of calling the
# external quote + image APIs; every request after that for the rest of
# the day — any employee, any number of them — just reads that row. This
# is what keeps 500 employees opening the dashboard from firing 500 calls
# at a third-party API, and guarantees they all see the same quote.
# =========================================================================

DEFAULT_QUOTE = {
    "quote": "Safety today. Stronger tomorrow.",
    "author": "Akrobat Team",
}

DEFAULT_BACKGROUND_URL = (
    "https://images.unsplash.com/photo-1497366754035-f200968a6e72"
    "?auto=format&fit=crop&w=1200&q=80"
)

# Used only if the *database itself* has zero prior rows to fall back to
# (fresh install / very first day) at the same time the external image
# API is unreachable. Ordinary "external API is down today" days fall
# back to the most recent row in daily_quotes instead of this list, so
# this is a last-resort pool, not the everyday background rotation.
FALLBACK_BACKGROUND_URLS = [
    DEFAULT_BACKGROUND_URL,
    "https://images.unsplash.com/photo-1521737711867-e3b97375f902?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1497215728101-856f4ea42174?auto=format&fit=crop&w=1200&q=80",
]


def _fetch_external_quote() -> dict | None:
    """Calls the public quote API (QUOTE_API_URL — zenquotes.io by
    default, keyless). Returns {"quote", "author"} or None on any
    failure (network error, timeout, non-200, unexpected shape) —
    callers fall back to the database / hardcoded default rather than
    ever letting a flaky third-party API take the dashboard down.
    """

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(QUOTE_API_URL)
            response.raise_for_status()
            payload = response.json()

        # zenquotes.io returns a list: [{"q": "...", "a": "...", ...}]
        if isinstance(payload, list) and payload:
            entry = payload[0]
            text = (entry.get("q") or "").strip()
            author = (entry.get("a") or "").strip()
            if text:
                return {"quote": text, "author": author or "Unknown"}

        # Tolerate a quotable.io-shaped response too ({"content", "author"})
        # in case QUOTE_API_URL is overridden via env to point at it.
        if isinstance(payload, dict) and payload.get("content"):
            return {
                "quote": payload["content"].strip(),
                "author": (payload.get("author") or "Unknown").strip(),
            }

        return None

    except Exception as e:
        logger.warning(f"Quote of the day: external quote API failed: {e}")
        return None


def _fetch_external_background() -> str | None:
    """Calls Pexels image search for a workplace/safety/teamwork photo
    and returns one image URL, or None if PEXELS_API_KEY isn't
    configured or the call fails for any reason.
    """

    if not PEXELS_API_KEY:
        return None

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": PEXELS_SEARCH_QUERY, "per_page": 30},
            )
            response.raise_for_status()
            payload = response.json()

        photos = payload.get("photos") or []
        if not photos:
            return None

        photo = random.choice(photos)
        src = photo.get("src") or {}
        return src.get("landscape") or src.get("large") or src.get("original")

    except Exception as e:
        logger.warning(f"Quote of the day: Pexels image API failed: {e}")
        return None


def _most_recent_stored_quote() -> dict | None:
    """The last successfully-saved daily_quotes row, used as the
    fallback when today needs a new row but the external APIs are down.
    """

    try:
        response = (
            supabase_admin.table("daily_quotes")
            .select("quote, author, background_url")
            .order("quote_date", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"Quote of the day: could not read fallback row: {e}")
        return None


def _serialize_quote_row(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "date": row.get("quote_date"),
        "quote": row.get("quote"),
        "author": row.get("author"),
        "background_url": row.get("background_url"),
        "source": row.get("source", "api"),
    }


def get_quote_of_day() -> dict:
    """Returns today's quote, creating it on the first call of the day.

    1. today's row already exists -> return it (no external calls)
    2. otherwise -> fetch quote + image externally, save, return
    3. any external failure -> reuse the most recent stored row
    4. database has no prior row at all -> hardcoded Akrobat default
    """

    try:
        today = date.today().isoformat()

        existing = (
            supabase_admin.table("daily_quotes")
            .select("*")
            .eq("quote_date", today)
            .limit(1)
            .execute()
        )
        if existing.data:
            return _serialize_quote_row(existing.data[0])

        # Nothing for today yet — this request pays the external-API cost.
        external_quote = _fetch_external_quote()
        external_background = _fetch_external_background()

        if external_quote and external_background:
            quote_text = external_quote["quote"]
            author = external_quote["author"]
            background_url = external_background
            source = "api"
        else:
            # One or both external calls failed — fall back to the most
            # recent stored quote so the card still changes to *something*
            # sensible rather than erroring, then to the hardcoded default
            # if the table is completely empty (fresh install).
            fallback = _most_recent_stored_quote()
            quote_text = (
                external_quote["quote"]
                if external_quote
                else (fallback or {}).get("quote", DEFAULT_QUOTE["quote"])
            )
            author = (
                external_quote["author"]
                if external_quote
                else (fallback or {}).get("author", DEFAULT_QUOTE["author"])
            )
            background_url = (
                external_background
                or (fallback or {}).get("background_url")
                or random.choice(FALLBACK_BACKGROUND_URLS)
            )
            source = "fallback"

        payload = {
            "quote_date": today,
            "quote": quote_text,
            "author": author,
            "background_url": background_url,
            "source": source,
        }

        try:
            inserted = supabase_admin.table("daily_quotes").insert(payload).execute()
            record = inserted.data[0]
        except Exception as insert_error:
            # Unique constraint on quote_date (sql/014_daily_quotes.sql) —
            # another concurrent request already won the race to create
            # today's row between our SELECT above and this INSERT. Re-read
            # instead of erroring, so the caller still gets today's quote.
            logger.info(
                "Quote of the day: insert lost the race for "
                f"{today}, re-reading existing row ({insert_error})"
            )
            existing_retry = (
                supabase_admin.table("daily_quotes")
                .select("*")
                .eq("quote_date", today)
                .limit(1)
                .execute()
            )
            if not existing_retry.data:
                raise
            record = existing_retry.data[0]

        return _serialize_quote_row(record)

    except Exception as e:
        logger.error(f"Quote of the day: unexpected failure: {e}")
        # Even a totally broken DB shouldn't 500 out a dashboard widget —
        # degrade to the hardcoded default rather than raising.
        return {
            "id": None,
            "date": date.today().isoformat(),
            "quote": DEFAULT_QUOTE["quote"],
            "author": DEFAULT_QUOTE["author"],
            "background_url": DEFAULT_BACKGROUND_URL,
            "source": "fallback",
        }