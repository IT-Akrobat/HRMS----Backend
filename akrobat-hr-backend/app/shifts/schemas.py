from pydantic import BaseModel
from typing import Optional


class CreateShiftRequest(BaseModel):

    shift_name: str

    start_time: str

    end_time: str

    working_hours: float

    break_duration: float

    grace_period: Optional[float] = 0

    status: Optional[str] = "Active"
