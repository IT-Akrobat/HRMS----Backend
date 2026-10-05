"""One-time fix: recompute attendance.late_minutes with each employee's own
timezone.

Why: before this change, lateness was judged against ONE company-wide
timezone (settings.timezone). Staff in the other country were measured
against the wrong clock, so e.g. Singapore employees were stored with
late_minutes = 0 even when they checked in late, and never showed up in
the dashboard's Late list. New check-ins are now correct; this script
repairs the rows already saved.

Only employees whose own timezone (work_location / nationality) differs
from the company timezone are touched -- everyone else's stored value was
already computed against the right clock.

Usage (from the backend root, with the same .env the API uses):

    python -m scripts.backfill_late_minutes --from 2026-09-01            # dry run
    python -m scripts.backfill_late_minutes --from 2026-09-01 --apply    # write

Options: --to YYYY-MM-DD (default: today), --apply (default is dry run).
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone

from app.core.database import supabase_admin
from app.attendance.services import (
    _get_attendance_rule,
    _get_company_timezone,
    _get_employee_shift,
    _late_minutes,
    _timezone_from_profile,
    _today_in_company_tz,
)

PAGE = 1000


def _fetch_all(build_query):
    rows, offset = [], 0
    while True:
        batch = build_query().range(offset, offset + PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def _naive_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    start = date.fromisoformat(args.date_from)
    end = date.fromisoformat(args.date_to) if args.date_to else _today_in_company_tz()

    company_tz = _get_company_timezone()
    rule = _get_attendance_rule()

    employees = _fetch_all(
        lambda: supabase_admin.table("employees")
        .select("id, full_name, work_location, nationality")
        .order("id")
    )
    affected = {}
    for emp in employees:
        zone = _timezone_from_profile(emp.get("work_location"), emp.get("nationality"))
        if zone and zone.key != company_tz.key:
            affected[emp["id"]] = (emp.get("full_name"), zone)

    print(f"Company timezone: {company_tz.key}")
    print(f"Employees on a different timezone: {len(affected)}")
    if not affected:
        return

    rows = _fetch_all(
        lambda: supabase_admin.table("attendance")
        .select("id, employee_id, attendance_date, check_in_time, late_minutes")
        .gte("attendance_date", start.isoformat())
        .lte("attendance_date", end.isoformat())
        .not_.is_("check_in_time", "null")
        .order("id")
    )

    changed = 0
    per_employee = defaultdict(int)
    for row in rows:
        emp_id = row["employee_id"]
        if emp_id not in affected:
            continue
        name, zone = affected[emp_id]
        for_date = date.fromisoformat(row["attendance_date"])
        shift = _get_employee_shift(emp_id, for_date)
        new_late = _late_minutes(
            _naive_utc(row["check_in_time"]), for_date, shift, rule, tz=zone
        )
        old_late = row.get("late_minutes") or 0
        if new_late == old_late:
            continue
        changed += 1
        per_employee[name] += 1
        print(f"{row['attendance_date']}  {name}: {old_late} -> {new_late} min")
        if args.apply:
            supabase_admin.table("attendance").update({"late_minutes": new_late}).eq(
                "id", row["id"]
            ).execute()

    verb = "Updated" if args.apply else "Would update"
    print(
        f"\n{verb} {changed} attendance row(s) across {len(per_employee)} employee(s)."
    )
    if not args.apply and changed:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
