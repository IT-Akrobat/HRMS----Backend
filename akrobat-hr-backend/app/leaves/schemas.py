from typing import Optional
from datetime import date

from pydantic import BaseModel


class CreateLeaveRequest(BaseModel):

    leave_type: str

    from_date: date

    to_date: date

    reason: str


class UpdateLeaveStatusRequest(BaseModel):

    status: str

    comments: Optional[str] = None
