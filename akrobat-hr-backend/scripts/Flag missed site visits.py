"""
Daily job: flag missed site visits for EVERY field employee automatically.

WHY THIS EXISTS
----------------
Today, "did this employee miss their assigned site?" is only ever
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

This script closes that gap by calling the exact same helper for every
field employee, on a schedule, independent of anyone opening the app.

USAGE
-----
Run manually to see what it would do (safe, read-mostly -- the
underlying helper only writes when it finds a genuine miss):

    python scripts/flag_missed_site_visits.py

Then put it on a daily schedule (cron / Task Scheduler / hosting
provider's "scheduled job" feature), e.g. once an hour in the evening
so it catches every shift's end time:

    # crontab -e
    0 18-23 * * * cd /path/to/akrobat-hr-backend && \
        /path/to/venv/bin/python scripts/flag_missed_site_visits.py >> \
        /var/log/site_visit_flag.log 2>&1

Running it more than once a day is safe -- an employee already flagged
is skipped instantly (already_missed short-circuit inside
_get_missed_site_assignments), and one still mid-shift is skipped too.
"""

import sys
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
    today = _today_in_company_tz()
    field_employee_ids = sorted(get_field_employee_ids())

    if not field_employee_ids:
        print("No field employees found. Nothing to check.")
        return

    print(f"Checking {len(field_employee_ids)} field employee(s) for {today}...\n")

    newly_flagged = []
    already_flagged = []
    errors = []

    for employee_id in field_employee_ids:
        try:
            missed = _get_missed_site_assignments(employee_id, today)
        except Exception as e:
            errors.append((employee_id, str(e)))
            print(f"  ERROR employee_id={employee_id}: {e}")
            continue

        for m in missed:
            print(
                f"  employee_id={employee_id}  site={m.get('location_name')}  "
                f"assignment_id={m.get('assignment_id')}"
            )

    print("\nDone.")
    if errors:
        print(f"{len(errors)} employee(s) errored -- see above.")


if __name__ == "__main__":
    main()
