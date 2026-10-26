from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class CreateSaturdaySwapRequest(BaseModel):
    # Normally-off Saturday (e.g. a 1st / 3rd Saturday) the employee WILL work.
    work_date: date
    # Normally-working Saturday (e.g. a 2nd / 4th Saturday) the employee skips.
    off_date: date
    reason: str = Field(min_length=3, max_length=500)


class UpdateSaturdaySwapStatusRequest(BaseModel):
    status: str  # Approved | Rejected
    comments: Optional[str] = Field(default=None, max_length=500)
