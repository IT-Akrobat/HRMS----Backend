from typing import Optional
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class CreateLeaveRequest(BaseModel):

    leave_type: str

    from_date: date

    to_date: date

    reason: str

    # Half-day application (only valid when from_date == to_date).
    half_day: bool = False


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


class SetLeaveUsedRequest(BaseModel):
    """HR correcting how many days an employee has already taken."""

    employee_id: UUID
    leave_type: str  # e.g. "SICK LEAVE"
    used_days: float = Field(ge=0, le=365)
    year: Optional[int] = None
    # Only needed when the employee has no balance row yet.
    total_days: Optional[float] = Field(default=None, ge=0, le=365)


class RecordHrManagedLeaveRequest(BaseModel):
    """HR / Super Admin recording Hospitalisation or Maternity leave."""

    employee_id: UUID
    leave_type: str  # "HOSPITALISATION LEAVE" or "MATERNITY LEAVE"
    from_date: date
    to_date: date
    reason: Optional[str] = None


class LeaveEntitlementInput(BaseModel):
    """One "days" input from the Create / Edit User form."""

    leave_type_id: UUID
    days: float = Field(ge=0, le=365)


class CreateLeaveTypeRequest(BaseModel):
    leave_name: str = Field(min_length=2, max_length=60)
    default_days: float = Field(default=0, ge=0, le=365)
    # ALL | MALE | FEMALE
    applies_to: str = "ALL"
    married_only: bool = False
    is_paid: bool = True
    description: Optional[str] = Field(default=None, max_length=200)
