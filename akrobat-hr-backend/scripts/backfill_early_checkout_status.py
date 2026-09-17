"""
Backfill: two data-hygiene corrections for existing attendance rows.

  status    Retag "obviously wrong" Half Day rows to Early Checkout.
  minutes   Recompute working_minutes / early_checkout_minutes /
            overtime_minutes / status from check_in_time / check_out_time
            using the current (fixed) calculation.

WHY THIS EXISTS
----------------
status
    check_out() (app/attendance/services.py) used to compute status as:

        "Half Day" if working_minutes < (minimum_work_minutes / 2) else "Present"

    That meant ANY checkout under the half-shift mark -- including someone
    who checked in and immediately checked out with 0 minutes worked --
    got tagged "Half Day", the same status as someone who genuinely
    worked close to half a shift. check_out() has since been fixed to
    use a three-tier split (Present / Half Day / Early Checkout), but
    that only affects *new* checkouts going forward -- status is written
    once at checkout time and never recalculated, so existing rows
    created under the old logic are still sitting there mislabeled.

minutes
    _compute_checkout_fields() (app/attendance/services.py) used to clamp
    a checkout that landed on/before check-in straight to 0 working
    minutes instead of recognising it as an overnight shift, and the
    "Log a missed checkout" modal (src/pages/hr-admin/Attendance.jsx)
    used to re-anchor a checkout edit on whatever date an *existing*
    (possibly already wrong) check_out_time happened to be on, which
    could push a record a full calendar day ahead on a second edit.
    Both are now fixed at the write path, but working_minutes is
    written once and never recalculated on its own, so rows already
    saved under the old logic are still sitting there wrong (0m "Early
    Checkout" for a real overnight shift, or 24h+ inflated totals).
    Those bad values are exactly what feeds Attendance Reports, the
    Reports & Analytics "Attendance" tab, and both pages' Excel/CSV
    exports -- they all just read the stored working_minutes column --
    so fixing the calculation code alone doesn't correct what those
    pages already show for past dates. `minutes` re-derives those
    columns for every checked-out row using the corrected
    _compute_checkout_fields, so historical reports and exports match
    the fixed logic too.

SCOPE (deliberately narrow)
----------------------------
status
    Does NOT recalculate every attendance row against the new
    thresholds -- only rows that are unambiguously wrong under the OLD
    formula too: status is "Half Day" but working_minutes is under the
    half-day threshold by a wide margin (checked in, then checked out
    almost immediately). That's the exact pattern from the bug report
    (0 minutes worked, tagged Half Day). Rows that are borderline under
    the new three-tier logic (e.g. genuinely worked 3-4 hours) are left
    alone, since re-litigating every historical Present/Half Day
    boundary is a separate, bigger decision than fixing the clear-cut
    mislabels.

minutes
    Only rows with both check_in_time and check_out_time are touched
    (nothing to recompute for a still-open/forgotten checkout). Only
    rows whose values actually change are written -- a row already
    correct under the fixed logic is left untouched (and doesn't count
    towards "updated").

Neither task writes audit_log entries for its corrections -- this is a
data-hygiene backfill for a bug, not a user-initiated attendance action.

USAGE
-----
Dry run first (default) -- prints what WOULD change, writes nothing:

    python scripts/backfill_early_checkout_status.py status
    python scripts/backfill_early_checkout_status.py minutes

Once you've reviewed the list, apply it for real:

    python scripts/backfill_early_checkout_status.py status --apply
    python scripts/backfill_early_checkout_status.py minutes --apply

Optionally narrow the window (defaults to all-time), either task:

    python scripts/backfill_early_checkout_status.py minutes --from 2026-01-01 --to 2026-09-09 --apply
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# so `app.core.*` / `app.attendance.*` imports resolve when run as a
# plain script, same pattern as scripts/create_super_admin.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import supabase_admin  # noqa: E402
from app.attendance.services import (  # noqa: E402
    _compute_checkout_fields,
    _get_attendance_rule,
    _get_employee_shift,
    _minimum_work_minutes,
)

# --- status ------------------------------------------------------------

NEW_STATUS = "Early Checkout"
OLD_STATUS = "Half Day"

# How far under the half-day threshold a row has to be to count as
# "obviously wrong" rather than a borderline case. 30 minutes catches
# near-immediate checkouts (0m, a few minutes) without touching anyone
# who was legitimately close to the half-day line under the old rule.
OBVIOUSLY_WRONG_MARGIN_MINUTES = 30


def find_status_candidates(from_date: date | None, to_date: date | None):
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


def run_status(args):
    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None

    candidates = find_status_candidates(from_date, to_date)

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


# --- minutes -------------------------------------------------------------

MINUTES_FIELDS = (
    "working_minutes",
    "early_checkout_minutes",
    "overtime_minutes",
    "status",
)


def find_minutes_candidates(from_date: date | None, to_date: date | None):
    query = (
        supabase_admin.table("attendance")
        .select(
            "id, employee_id, attendance_date, check_in_time, check_out_time, "
            "break_minutes, working_minutes, early_checkout_minutes, "
            "overtime_minutes, status"
        )
        .not_.is_("check_in_time", "null")
        .not_.is_("check_out_time", "null")
    )
    if from_date:
        query = query.gte("attendance_date", from_date.isoformat())
    if to_date:
        query = query.lte("attendance_date", to_date.isoformat())

    rows = query.execute().data or []
    candidates = []

    for row in rows:
        try:
            computed = _compute_checkout_fields(
                row["employee_id"],
                date.fromisoformat(row["attendance_date"]),
                datetime.fromisoformat(row["check_in_time"]),
                datetime.fromisoformat(row["check_out_time"]),
                row.get("break_minutes") or 0,
            )
        except Exception as e:  # malformed row -- skip, don't crash the run
            print(f"  skipping attendance.id={row['id']} -- {e}")
            continue

        before = {field: row.get(field) for field in MINUTES_FIELDS}
        if before == computed:
            continue  # already correct under the fixed logic

        candidates.append(
            {
                "id": row["id"],
                "employee_id": row["employee_id"],
                "attendance_date": row["attendance_date"],
                "before": before,
                "after": computed,
            }
        )

    return candidates


def run_minutes(args):
    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None

    candidates = find_minutes_candidates(from_date, to_date)

    if not candidates:
        print("No rows need recalculating. Nothing to do.")
        return

    print(f"Found {len(candidates)} row(s) to recalculate:\n")
    for c in candidates:
        b, a = c["before"], c["after"]
        print(
            f"  attendance.id={c['id']}  employee_id={c['employee_id']}  "
            f"date={c['attendance_date']}\n"
            f"      before: working={b['working_minutes']}m  "
            f"status={b['status']}\n"
            f"      after:  working={a['working_minutes']}m  "
            f"status={a['status']}"
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
        supabase_admin.table("attendance").update(c["after"]).eq(
            "id", c["id"]
        ).execute()
        updated += 1

    print(f"Done. {updated} row(s) recalculated.")


# --- CLI -----------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Data-hygiene backfills for existing attendance rows."
    )
    subparsers = parser.add_subparsers(dest="task", required=True)

    status_parser = subparsers.add_parser(
        "status", help="Retag obviously-wrong Half Day rows to Early Checkout."
    )
    status_parser.add_argument("--apply", action="store_true")
    status_parser.add_argument("--from", dest="from_date", default=None)
    status_parser.add_argument("--to", dest="to_date", default=None)
    status_parser.set_defaults(func=run_status)

    minutes_parser = subparsers.add_parser(
        "minutes",
        help="Recompute working_minutes/overtime/status from check-in/out "
        "using the fixed calculation.",
    )
    minutes_parser.add_argument("--apply", action="store_true")
    minutes_parser.add_argument("--from", dest="from_date", default=None)
    minutes_parser.add_argument("--to", dest="to_date", default=None)
    minutes_parser.set_defaults(func=run_minutes)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
