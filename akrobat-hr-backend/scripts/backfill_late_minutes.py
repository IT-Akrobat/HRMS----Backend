"""One-time fix: recompute attendance.late_minutes using the timezone each
check-in actually happened in.

Why: lateness used to be judged against the company timezone, or against the
employee's nationality. Staff working in the other country -- e.g. Indian
nationals working in the Singapore office -- were measured against the wrong
clock, stored with late_minutes = 0 even when they checked in late, and never
showed up in the dashboard's Late list. New check-ins are now judged by the
check-in GPS (then work_location, then the company timezone); this script
repairs the rows already saved, using the same rule.

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
    _today_in_company_tz,
)
from app.attendance.tz_helper import resolve_record_timezone

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
        .select("id, full_name, work_location")
        .order("id")
    )
    people = {e["id"]: e for e in employees}
    print(f"Company timezone: {company_tz.key}")

    rows = _fetch_all(
        lambda: supabase_admin.table("attendance")
        .select(
            "id, employee_id, attendance_date, check_in_time, late_minutes, "
            "check_in_latitude, check_in_longitude, "
            "check_out_latitude, check_out_longitude"
        )
        .gte("attendance_date", start.isoformat())
        .lte("attendance_date", end.isoformat())
        .not_.is_("check_in_time", "null")
        .order("id")
    )

    changed = 0
    per_employee = defaultdict(int)
    for row in rows:
        emp = people.get(row["employee_id"])
        if not emp:
            continue
        name = emp.get("full_name")
        zone = resolve_record_timezone(row, emp.get("work_location"), company_tz)
        for_date = date.fromisoformat(row["attendance_date"])
        shift = _get_employee_shift(row["employee_id"], for_date)
        new_late = _late_minutes(
            _naive_utc(row["check_in_time"]), for_date, shift, rule, tz=zone
        )
        old_late = row.get("late_minutes") or 0
        if new_late == old_late:
            continue
        changed += 1
        per_employee[name] += 1
        print(
            f"{row['attendance_date']}  {name} [{zone.key}]: "
            f"{old_late} -> {new_late} min"
        )
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
