"""
Overtime (OT) for on-site staff who are eligible for additional salary
(employees.ot_eligible = true; see sql/034_ot_eligible_staff.sql).

Rule (clock-time based, NOT "hours worked"):
  * OT counts only after the employee's shift end time
    (Mon-Fri: employees.ot_weekday_end, Sat: employees.ot_saturday_end).
  * Whole hours only. For each hour, the leftover minutes must reach 41
    to round up to the next hour; 40 or less is dropped.
        0h40m -> 0h    0h41m -> 1h
        1h40m -> 1h    1h41m -> 2h    2h40m -> 2h    2h41m -> 3h
  * The raw minutes after shift end are always returned too, so HR can
    still see e.g. "35m after shift, 0h OT".
"""

from datetime import date, datetime, time, timezone
from typing import Optional

OT_ROUND_UP_AT_MINUTES = 41


def ot_hours_from_minutes(after_shift_minutes: int) -> int:
    minutes = max(0, int(after_shift_minutes or 0))
    hours, leftover = divmod(minutes, 60)
    if leftover >= OT_ROUND_UP_AT_MINUTES:
        hours += 1
    return hours


def _parse_time(value) -> Optional[time]:
    if not value:
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def compute_ot(
    attendance_date,
    check_out_time,
    weekday_end,
    saturday_end,
    tz,
) -> dict:
    """
    Returns {"after_shift_minutes": int, "ot_hours": int}.
    check_out_time is the stored value (naive UTC string/datetime);
    tz is the company/employee timezone the shift times are written in.
    Sunday and rows without a checkout/cut-off return zeros.
    """
    zero = {"after_shift_minutes": 0, "ot_hours": 0}
    if not check_out_time or not attendance_date:
        return zero

    day = (
        attendance_date
        if isinstance(attendance_date, date)
        else date.fromisoformat(str(attendance_date)[:10])
    )
    if day.weekday() == 6:  # Sunday: no OT rule defined
        return zero

    cutoff_time = _parse_time(saturday_end if day.weekday() == 5 else weekday_end)
    if not cutoff_time:
        return zero

    out = (
        check_out_time
        if isinstance(check_out_time, datetime)
        else datetime.fromisoformat(str(check_out_time))
    )
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    local_out = out.astimezone(tz)

    cutoff = datetime.combine(day, cutoff_time).replace(tzinfo=tz)
    after = int((local_out - cutoff).total_seconds() // 60)
    after = max(0, after)
    return {"after_shift_minutes": after, "ot_hours": ot_hours_from_minutes(after)}
