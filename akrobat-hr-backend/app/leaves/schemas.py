from typing import Optional
from datetime import date
from uuid import UUID

from pydantic import BaseModel


class CreateLeaveRequest(BaseModel):

    leave_type: str

    from_date: date

    to_date: date

    reason: str


class UpdateLeaveStatusRequest(BaseModel):

    status: str

    comments: Optional[str] = None


# ==========================================
# Leave Policy Engine
# ==========================================


class AssignLeaveTierRequest(BaseModel):
    employee_id: UUID
    leave_type: str  # e.g. "ANNUAL LEAVE", "CHILDCARE LEAVE"
    tier_id: UUID


class CreditReplacementLeaveRequest(BaseModel):
    employee_id: UUID
    public_holiday_date: date


class GenerateYearlyBalancesRequest(BaseModel):
    year: Optional[int] = None


class GrantLeaveBalanceRequest(BaseModel):
    employee_id: UUID
    leave_type: str  # e.g. "COMPASSIONATE LEAVE" — must be a 'fixed' mode type
    days: int
    year: Optional[int] = None
