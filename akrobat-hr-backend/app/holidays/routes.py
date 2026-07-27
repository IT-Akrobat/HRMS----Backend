from typing import Optional

from fastapi import APIRouter, Query

from app.holidays.schemas import CreateHolidayRequest

from app.holidays.services import (
    create_holiday,
    get_holidays,
    get_holiday,
    update_holiday,
    delete_holiday,
)

router = APIRouter(prefix="/holidays", tags=["Holidays"])


@router.post("/")
def create(data: CreateHolidayRequest):
    return create_holiday(data)


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
