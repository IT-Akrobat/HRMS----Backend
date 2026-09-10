"""
Backfill: retag "obviously wrong" Half Day rows to Early Checkout.

WHY THIS EXISTS
----------------
check_out() (app/attendance/services.py) used to compute status as:

    "Half Day" if working_minutes < (minimum_work_minutes / 2) else "Present"

That meant ANY checkout under the half-shift mark -- including someone
who checked in and immediately checked out with 0 minutes worked -- got
tagged "Half Day", the same status as someone who genuinely worked close
to half a shift. check_out() has since been fixed to use a three-tier
split (Present / Half Day / Early Checkout), but that only affects *new*
checkouts going forward -- status is written once at checkout time and
never recalculated, so existing rows created under the old logic are
still sitting there mislabeled.

SCOPE (deliberately narrow)
----------------------------
This script does NOT recalculate every attendance row against the new
thresholds -- only rows that are unambiguously wrong under the OLD
formula too: status is "Half Day" but working_minutes is under the
half-day threshold by a wide margin (checked in, then checked out
almost immediately). That's the exact pattern from the bug report (0
minutes worked, tagged Half Day). Rows that are borderline under the
new three-tier logic (e.g. genuinely worked 3-4 hours) are left alone,
since re-litigating every historical Present/Half Day boundary is a
separate, bigger decision than fixing the clear-cut mislabels.

Only `attendance.status` is updated -- no audit_log entries are written
for these corrections (this is a data-hygiene backfill for a bug, not a
user-initiated attendance action).

USAGE
-----
Dry run first (default) -- prints what WOULD change, writes nothing:

    python scripts/backfill_early_checkout_status.py

Once you've reviewed the list, apply it for real:

    python scripts/backfill_early_checkout_status.py --apply

Optionally narrow the window (defaults to all-time):

    python scripts/backfill_early_checkout_status.py --from 2026-01-01 --to 2026-09-09 --apply
"""

import argparse
import sys
from datetime import date
from pathlib import Path

# so `app.core.*` / `app.attendance.*` imports resolve when run as a
# plain script, same pattern as scripts/create_super_admin.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import supabase_admin  # noqa: E402
from app.attendance.services import (  # noqa: E402
    _get_attendance_rule,
    _get_employee_shift,
    _minimum_work_minutes,
)

NEW_STATUS = "Early Checkout"
OLD_STATUS = "Half Day"

# How far under the half-day threshold a row has to be to count as
# "obviously wrong" rather than a borderline case. 30 minutes catches
# near-immediate checkouts (0m, a few minutes) without touching anyone
# who was legitimately close to the half-day line under the old rule.
OBVIOUSLY_WRONG_MARGIN_MINUTES = 30


def find_candidates(from_date: date | None, to_date: date | None):
    query = (
        supabase_admin.table("attendance")
        .select("id, employee_id, attendance_date, working_minutes, status")
        .eq("status", OLD_STATUS)
        .not_.is_("check_out_time", "null")
    )
    if from_date:
        query = query.gte("attendance_date", from_date.isoformat())
    if to_date:
        query = query.lte("attendance_date", to_date.isoformat())

    rows = query.execute().data or []

    rule = _get_attendance_rule()
    candidates = []

    for row in rows:
        employee_id = row.get("employee_id")
        attendance_date = date.fromisoformat(row["attendance_date"])
        working_minutes = row.get("working_minutes") or 0

        shift = _get_employee_shift(employee_id, attendance_date)
        minimum_work_minutes = _minimum_work_minutes(shift, rule)
        half_day_threshold = minimum_work_minutes / 2

        if working_minutes < (half_day_threshold - OBVIOUSLY_WRONG_MARGIN_MINUTES):
            candidates.append(
                {
                    "id": row["id"],
                    "employee_id": employee_id,
                    "attendance_date": row["attendance_date"],
                    "working_minutes": working_minutes,
                    "half_day_threshold": half_day_threshold,
                }
            )

    return candidates


def main():
    parser = argparse.ArgumentParser(
        description="Retag obviously-wrong Half Day rows to Early Checkout."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the updates. Without this flag, the script "
        "only prints what would change.",
    )
    parser.add_argument("--from", dest="from_date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None

    candidates = find_candidates(from_date, to_date)

    if not candidates:
        print("No obviously-wrong Half Day rows found. Nothing to do.")
        return

    print(
        f"Found {len(candidates)} row(s) to retag {OLD_STATUS!r} -> {NEW_STATUS!r}:\n"
    )
    for c in candidates:
        print(
            f"  attendance.id={c['id']}  employee_id={c['employee_id']}  "
            f"date={c['attendance_date']}  worked={c['working_minutes']}m  "
            f"(half-day threshold was {c['half_day_threshold']:.0f}m)"
        )

    if not args.apply:
        print(
            f"\nDry run only -- no rows were changed. Re-run with --apply "
            f"to write these {len(candidates)} update(s)."
        )
        return

    print(f"\nApplying {len(candidates)} update(s)...")
    updated = 0
    for c in candidates:
        supabase_admin.table("attendance").update({"status": NEW_STATUS}).eq(
            "id", c["id"]
        ).execute()
        updated += 1

    print(f"Done. {updated} row(s) retagged to {NEW_STATUS!r}.")


if __name__ == "__main__":
    main()
