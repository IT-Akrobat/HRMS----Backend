from pydantic import BaseModel
from datetime import date


class CreateHolidayRequest(BaseModel):
    holiday_name: str
    holiday_date: date
    description: str | None = None
    # 'SG' or 'IN' today; free text so more country calendars can be
    # added later without a schema change. Defaults to 'SG' (company HQ).
    country: str = "SG"