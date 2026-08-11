from pydantic import BaseModel
from datetime import date
from typing import Optional


class CreateHolidayRequest(BaseModel):
    holiday_name: str
    holiday_date: date
    description: str | None = None
    # 'SG' or 'IN' today; free text so more country calendars can be
    # added later without a schema change. Defaults to 'SG' (company HQ).
    country: str = "SG"


class BulkImportHolidayItem(BaseModel):
    holiday_name: str
    # The real calendar date the holiday falls on, e.g. from the MOM
    # list (https://www.mom.gov.sg/employment-practices/public-holidays).
    # If this lands on a Sunday, holiday_date is auto-computed as the
    # following Monday (MOM's Sunday-shift rule) and raw_holiday_date
    # keeps the real date so Saturday-PH detection (Replacement Leave)
    # still works off the actual day of week.
    raw_holiday_date: date
    description: Optional[str] = None
    country: str = "SG"


class BulkImportHolidaysRequest(BaseModel):
    holidays: list[BulkImportHolidayItem]
