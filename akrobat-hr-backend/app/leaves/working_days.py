"""
Working-day counting for leave requests.

A leave request used to be counted as raw calendar days
((to - from) + 1), so a Mon-Tue-next-week request came out as 8 days even
though the employee only works 6 of them. The rules applied here:

  * Sunday                -> never counted.
  * Public holiday        -> never counted (the employee's country calendar:
                             Singapore holidays for Singapore-based staff).
                             holidays.holiday_date is the OBSERVED date, i.e.
                             already shifted Sunday -> Monday.
  * Saturday              -> not counted if the employee doesn't work that
                             Saturday (works_saturday = false, or an
                             "alternate Saturday" employee on a 1st/3rd/5th
                             Saturday); 0.5 if their Saturday shift is a half
                             day; 1.0 if it is a full day.
  * Monday - Friday       -> 1.0.
"""

from datetime import date, timedelta
from typing import Optional

from app.core.database import supabase_admin
from app.core.exceptions import bad_request
from app.core.logger import logger

# A Saturday shift shorter than this many hours is a half day
# (Office 3.5h / Inspection 4h are half days; Operation 7h is a full day).
HALF_DAY_MAX_HOURS = 5.0

_SG_WORDS = ("singapore", "singaporean")
_IN_WORDS = ("india", "indian")


def detect_holiday_country(employee: Optional[dict]) -> str:
    """
    'SG' or 'IN'. Same order as the attendance timezone lookup:
    work_location first, then nationality. Singapore is HQ and the default
    when neither field says otherwise.
    """
    employee = employee or {}
    for field in ("work_location", "nationality"):
        text = str(employee.get(field) or "").lower()
        if any(w in text for w in _SG_WORDS):
            return "SG"
        if any(w in text for w in _IN_WORDS):
            return "IN"
    return "SG"


def _holiday_dates(country: str, start: date, end: date) -> set:
    # Imported here: holidays.services pulls in notifications etc.
    from app.holidays.services import _country_variants

    rows = (
        supabase_admin.table("holidays")
        .select("holiday_date")
        .in_("country", _country_variants(country))
        .gte("holiday_date", start.isoformat())
        .lte("holiday_date", end.isoformat())
        .execute()
        .data
        or []
    )
    out = set()
    for r in rows:
        try:
            out.add(date.fromisoformat(str(r["holiday_date"])[:10]))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _shift_hours(shift: dict) -> Optional[float]:
    hours = shift.get("working_hours")
    try:
        if hours is not None and float(hours) > 0:
            return float(hours)
    except (TypeError, ValueError):
        pass
    start, end = shift.get("start_time"), shift.get("end_time")
    try:
        sh, sm = [int(x) for x in str(start).split(":")[:2]]
        eh, em = [int(x) for x in str(end).split(":")[:2]]
        diff = (eh * 60 + em) - (sh * 60 + sm)
        return diff / 60 if diff > 0 else None
    except (TypeError, ValueError):
        return None


def _saturday_value(employee_id: str, day: date) -> float:
    """0 = off, 0.5 = half day, 1 = full day, for one Saturday."""
    # Reuses the attendance shift resolver so leave and attendance can never
    # disagree about whether someone works a given Saturday. It returns None
    # when the employee is off that Saturday (works_saturday false,
    # alternate-Saturday off-week).
    from app.attendance.services import _get_employee_shift

    shift = _get_employee_shift(employee_id, day)
    if not shift:
        return 0.0
    hours = _shift_hours(shift)
    if hours is not None and hours < HALF_DAY_MAX_HOURS:
        return 0.5
    return 1.0


def calculate_leave_days(
    employee: dict,
    from_date: date,
    to_date: date,
    half_day: bool = False,
) -> dict:
    """
    Returns {"total_days": float, "country": str, "breakdown": [...]}.
    `employee` needs id, work_location, nationality.
    """
    if to_date < from_date:
        bad_request("to_date must be on or after from_date.")

    country = detect_holiday_country(employee)
    try:
        holidays = _holiday_dates(country, from_date, to_date)
    except Exception as e:
        logger.error(f"Unable to load holidays for leave count: {e}")
        holidays = set()

    breakdown = []
    total = 0.0
    saturday_cache = {}
    day = from_date
    while day <= to_date:
        weekday = day.weekday()  # Mon=0 ... Sun=6
        if weekday == 6:
            value, reason = 0.0, "Sunday"
        elif day in holidays:
            value, reason = 0.0, "Public holiday"
        elif weekday == 5:
            if day not in saturday_cache:
                saturday_cache[day] = _saturday_value(employee["id"], day)
            value = saturday_cache[day]
            reason = (
                "Saturday (not working)"
                if value == 0
                else "Saturday (half day)" if value == 0.5 else "Saturday"
            )
        else:
            value, reason = 1.0, None
        total += value
        breakdown.append({"date": day.isoformat(), "days": value, "note": reason})
        day += timedelta(days=1)

    if half_day:
        if from_date != to_date:
            bad_request("A half-day leave must be for a single date.")
        total = min(total, 0.5)

    if total <= 0:
        bad_request(
            "The selected dates have no working days "
            "(weekends / public holidays are not counted)."
        )

    return {"total_days": total, "country": country, "breakdown": breakdown}
