from typing import Optional

from fastapi import APIRouter, Query, Depends, File, UploadFile

from app.holidays.schemas import CreateHolidayRequest, BulkImportHolidaysRequest

from app.holidays.services import (
    create_holiday,
    get_holidays,
    get_holiday,
    update_holiday,
    delete_holiday,
    bulk_import_holidays,
    import_holidays_from_excel,
    get_saturday_holidays,
    get_holiday_reminder_status,
)
from app.core.rbac import require_permission
from app.core.security import get_current_user

router = APIRouter(prefix="/holidays", tags=["Holidays"])


@router.post("/")
def create(
    data: CreateHolidayRequest,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    return create_holiday(data)


@router.post("/bulk-import")
def bulk_import(
    data: BulkImportHolidaysRequest,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    """HR: populate holidays for a year from an external list (e.g. MOM's
    public holiday list). Sunday-shift is applied automatically -- pass
    each holiday's real calendar date as raw_holiday_date."""
    return bulk_import_holidays(data.holidays)


@router.post("/bulk-import/excel")
def bulk_import_excel(
    file: UploadFile = File(...),
    country: str = Query(
        "SG",
        description="Fallback country for rows that don't have their own Country column.",
    ),
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    """HR/Super Admin: same as POST /holidays/bulk-import, but from an
    uploaded .xlsx file instead of a JSON body -- for the "Upload Excel"
    button on the Holidays screen. Expected columns: Holiday Name, Date,
    Description (optional), Country (optional)."""
    return import_holidays_from_excel(file, default_country=country)


@router.get("/saturday")
def saturday_holidays(
    country: str = Query("SG"),
    year: Optional[int] = Query(None),
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    """Public holidays that actually fell on a Saturday -- the
    Replacement Leave crediting candidates."""
    return get_saturday_holidays(country=country, year=year)


@router.get("/")
def get_all(
    country: Optional[str] = Query(
        None,
        description="Filter by country calendar, e.g. 'SG' or 'IN'. Omit for all.",
    ),
    user=Depends(get_current_user),
):
    return get_holidays(country=country)


# Self-service "is a holiday coming up?" check -- polled by the frontend
# (Header.jsx, alongside the attendance/celebrations reminder polls).
# Sends an advance "tomorrow is a holiday" notice the day before, plus a
# same-day fallback notice, gated by the requesting employee's own
# "Holiday reminders" toggle in Settings -> Notifications. Registered
# before /{holiday_id} so "reminder-check" isn't swallowed by the path
# parameter. See get_holiday_reminder_status() docstring for full
# conditions.
@router.get("/reminder-check")
def holiday_reminder_check(user=Depends(get_current_user)):
    return get_holiday_reminder_status(user.id)


@router.get("/{holiday_id}")
def get_one(holiday_id: str, user=Depends(get_current_user)):
    return get_holiday(holiday_id)


@router.put("/{holiday_id}")
def update(
    holiday_id: str,
    data: dict,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    return update_holiday(holiday_id, data)


@router.delete("/{holiday_id}")
def delete(holiday_id: str, user=Depends(require_permission("EDIT_EMPLOYEE"))):
    return delete_holiday(holiday_id)
