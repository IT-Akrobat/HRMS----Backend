from typing import Optional

from fastapi import APIRouter, Query, Depends

from app.holidays.schemas import CreateHolidayRequest, BulkImportHolidaysRequest

from app.holidays.services import (
    create_holiday,
    get_holidays,
    get_holiday,
    update_holiday,
    delete_holiday,
    bulk_import_holidays,
    get_saturday_holidays,
)
from app.core.rbac import require_permission

router = APIRouter(prefix="/holidays", tags=["Holidays"])


@router.post("/")
def create(data: CreateHolidayRequest):
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
):
    return get_holidays(country=country)


@router.get("/{holiday_id}")
def get_one(holiday_id: str):
    return get_holiday(holiday_id)


@router.put("/{holiday_id}")
def update(holiday_id: str, data: dict):
    return update_holiday(holiday_id, data)


@router.delete("/{holiday_id}")
def delete(holiday_id: str):
    return delete_holiday(holiday_id)
