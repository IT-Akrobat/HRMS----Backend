"""
Tiny, dependency-light lookup used by app/attendance/services.py.

Kept in its own module (no imports from attendance / leaves) so the
attendance resolver can call it without creating an import cycle.
"""

from datetime import date
from typing import Optional

from app.core.database import supabase_admin
from app.core.logger import logger

WORK = "WORK"  # approved swap: this normally-off Saturday is a working day
OFF = "OFF"  # approved swap: this normally-working Saturday is a week-off


def get_swap_state(employee_id: str, for_date: date) -> Optional[str]:
    """
    Returns "WORK", "OFF" or None for `employee_id` on `for_date`, looking
    only at APPROVED swaps. Never raises -- if the lookup fails (e.g. the
    migration hasn't been run yet) the employee simply keeps their normal
    schedule.
    """
    if for_date.weekday() != 5:
        return None
    iso = for_date.isoformat()
    try:
        rows = (
            supabase_admin.table("saturday_swaps")
            .select("work_date, off_date")
            .eq("employee_id", employee_id)
            .eq("status", "Approved")
            .or_(f"work_date.eq.{iso},off_date.eq.{iso}")
            .limit(2)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.error(f"Saturday swap lookup failed for {employee_id}: {e}")
        return None

    for row in rows:
        if str(row.get("off_date"))[:10] == iso:
            return OFF
    for row in rows:
        if str(row.get("work_date"))[:10] == iso:
            return WORK
    return None
