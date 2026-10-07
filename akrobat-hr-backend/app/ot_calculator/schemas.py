from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class OtAdjustmentItem(BaseModel):
    employee_id: str
    attendance_date: date
    # None / omitted = remove the manual edit (go back to the auto OT).
    manual_ot_hours: Optional[float] = Field(default=None, ge=0, le=24)
    note: Optional[str] = Field(default=None, max_length=300)


class SaveOtAdjustmentsRequest(BaseModel):
    items: List[OtAdjustmentItem] = Field(min_length=1, max_length=500)
