"""
Flag missed site visits for EVERY field employee -- either for TODAY
(what you'd put on a daily schedule) or for a SPECIFIC past date (a
one-time backfill for a day the automatic check didn't exist for yet).

WHY THIS EXISTS
----------------
Normally, "did this employee miss their assigned site?" is only ever
checked inside two request handlers in app/attendance/services.py:

  - get_site_visit_compliance_status()   -- fires when the EMPLOYEE's
    own dashboard (SiteVisitCard) happens to poll it
  - get_team_site_visit_status_today()   -- fires when the MANAGER
    happens to open the Attendance / Team page

Both call the same core helper, _get_missed_site_assignments(), which
persists `is_missed = true` on the employee_site_assignments row once
it detects a missed visit (see sql/032.sql). But if NEITHER page is
opened during the window after that employee's shift ends and before
midnight, the check simply never runs for that day -- and the next
day's check only looks at "today", so that miss is gone forever, with
no locked "Arrived" button and no "Missed" badge for the manager.

This script calls the exact same helper for every field employee, for
whichever date you give it, independent of anyone opening the app.

USAGE
-----
Daily use (checks TODAY -- this is what the scheduled job in main.py
also does automatically; running this by hand is just for visibility):

    python scripts/flag_missed_site_visits.py

One-time backfill for a past date the check missed (e.g. before this
script/scheduler existed, or a day the server was down):

    python scripts/flag_missed_site_visits.py 2026-09-17

Put the no-argument form on a daily schedule if you're not using the
in-app APScheduler job, e.g. once an hour in the evening so it catches
every shift's end time:

    # crontab -e
    0 18-23 * * * cd /path/to/akrobat-hr-backend && \\
        /path/to/venv/bin/python scripts/flag_missed_site_visits.py >> \\
        /var/log/site_visit_flag.log 2>&1

Running it more than once, for the same or different dates, is safe --
an employee already flagged is skipped instantly (already_missed
short-circuit inside _get_missed_site_assignments), and one still
mid-shift (for that date) is skipped too.
"""

import sys
from datetime import date
from pathlib import Path

# so `app.core.*` / `app.attendance.*` imports resolve when run as a
# plain script, same pattern as scripts/backfill_early_checkout_status.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.helpers.employee_helper import get_field_employee_ids  # noqa: E402
from app.attendance.services import (  # noqa: E402
    _get_missed_site_assignments,
    _today_in_company_tz,
)


def main():
    if len(sys.argv) > 1:
        target_date = date.fromisoformat(sys.argv[1])
        mode = "backfill"
    else:
        target_date = _today_in_company_tz()
        mode = "daily check"

    field_employee_ids = sorted(get_field_employee_ids())

    if not field_employee_ids:
        print("No field employees found. Nothing to check.")
        return

    print(
        f"[{mode}] Checking {len(field_employee_ids)} field employee(s) "
        f"for {target_date}...\n"
    )

    found_any = False
    errors = []

    for employee_id in field_employee_ids:
        try:
            missed = _get_missed_site_assignments(employee_id, target_date)
        except Exception as e:
            errors.append((employee_id, str(e)))
            print(f"  ERROR employee_id={employee_id}: {e}")
            continue

        for m in missed:
            found_any = True
            print(
                f"  FLAGGED  employee_id={employee_id}  "
                f"site={m.get('location_name')}  "
                f"assignment_id={m.get('assignment_id')}"
            )

    if not found_any and not errors:
        print("Nothing to flag -- no missed visits found for that date.")

    print("\nDone.")
    if errors:
        print(f"{len(errors)} employee(s) errored -- see above.")


if __name__ == "__main__":
    main()
