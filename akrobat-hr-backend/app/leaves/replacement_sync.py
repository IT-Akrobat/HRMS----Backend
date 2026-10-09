"""
Automatic Replacement Leave (RL) credits for public holidays.

Policy:
  * Holiday on a Sunday    -> everyone gets 1 RL.
  * Holiday on a Saturday  -> everyone is off that day (no leave is counted),
                              and RL depends on their Saturday schedule:
                                not working Saturday   -> 1.0 RL
                                half-day Saturday      -> 0.5 RL
                                full-day Saturday      -> 0 RL
  * Holiday Mon-Fri        -> normal holiday, no RL.

There is no background scheduler in this backend, so credits are granted
lazily (idempotently) whenever RL is read or used: a holiday is credited once
its date has arrived, for every employee who had joined by then. A credit
already on file for (employee, holiday date) -- manual or automatic -- is
never duplicated.
"""

from datetime import date
from typing import Iterable, Optional

from app.core.database import supabase_admin
from app.core.logger import logger
from app.leaves.working_days import detect_holiday_country, _saturday_value

# Holidays before this date are not auto-credited. 2026 Replacement Leave was
# set by hand from HR's sheet (scripts/fix_rl_mc_balances.py), so automatic
# crediting only starts with 2027 holidays -- otherwise this sync would add
# 2026 Saturday/Sunday holiday credits on top of the sheet figures.
AUTO_CREDIT_FROM = date(2027, 1, 1)


def _d(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _expiry(holiday: date) -> date:
    try:
        return holiday.replace(year=holiday.year + 1)
    except ValueError:  # 29 Feb
        return holiday.replace(year=holiday.year + 1, day=28)


def credit_days_for(employee_id: str, holiday_day: date) -> float:
    weekday = holiday_day.weekday()
    if weekday == 6:
        return 1.0
    if weekday == 5:
        return max(0.0, 1.0 - _saturday_value(employee_id, holiday_day))
    return 0.0


def sync_replacement_credits(employee_ids: Optional[Iterable[str]] = None) -> int:
    """Grants any missing automatic credits. Returns how many were created.
    Never raises -- bookkeeping must not break leave screens."""
    try:
        from app.holidays.services import _normalize_country

        today = date.today()

        holiday_rows = (
            supabase_admin.table("holidays")
            .select("holiday_date, raw_holiday_date, country")
            .lte("holiday_date", today.isoformat())
            .gte("holiday_date", AUTO_CREDIT_FROM.isoformat())
            .execute()
            .data
            or []
        )
        # (country -> [(real_date, observed_date)]) for Saturdays/Sundays only
        by_country: dict = {}
        for h in holiday_rows:
            observed = _d(h.get("holiday_date"))
            real = _d(h.get("raw_holiday_date")) or observed
            if not real or real.weekday() not in (5, 6):
                continue
            by_country.setdefault(_normalize_country(h.get("country")), set()).add(
                (real, observed)
            )
        if not by_country:
            return 0

        query = supabase_admin.table("employees").select("*")
        ids = list(employee_ids) if employee_ids is not None else None
        if ids is not None:
            if not ids:
                return 0
            query = query.in_("id", ids)
        employees = [
            e
            for e in (query.execute().data or [])
            if e.get("is_active") is not False
            and str(e.get("employment_status") or "Active").lower()
            not in ("terminated", "resigned", "inactive")
        ]
        if not employees:
            return 0

        existing_query = supabase_admin.table("leave_replacement_credits").select(
            "employee_id, public_holiday_date"
        )
        if ids is not None:
            existing_query = existing_query.in_("employee_id", ids)
        existing = {
            (r["employee_id"], str(r["public_holiday_date"])[:10])
            for r in (existing_query.execute().data or [])
        }

        new_rows = []
        for emp in employees:
            joined = _d(emp.get("joining_date"))
            country = detect_holiday_country(emp)
            for real, observed in sorted(by_country.get(country, ())):
                if joined and joined > real:
                    continue
                keys = {(emp["id"], real.isoformat())}
                if observed:
                    keys.add((emp["id"], observed.isoformat()))
                if keys & existing:
                    continue
                days = credit_days_for(emp["id"], real)
                if days <= 0:
                    continue
                new_rows.append(
                    {
                        "employee_id": emp["id"],
                        "public_holiday_date": real.isoformat(),
                        "credited_by": None,
                        "credited_date": today.isoformat(),
                        "expiry_date": _expiry(real).isoformat(),
                        "used": False,
                        "days": days,
                        "used_days": 0,
                    }
                )
                existing.add((emp["id"], real.isoformat()))

        for i in range(0, len(new_rows), 200):
            supabase_admin.table("leave_replacement_credits").insert(
                new_rows[i : i + 200]
            ).execute()
        return len(new_rows)
    except Exception as e:
        logger.error(f"Replacement leave auto-credit failed: {e}")
        return 0
