from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

REASON_CATEGORIES = [
    "Better opportunity",
    "Higher studies",
    "Relocation",
    "Personal reasons",
    "Health reasons",
    "Compensation",
    "Work environment",
    "Retirement",
    "Other",
]


class ResignationCreate(BaseModel):
    employee_id: str  # employees.id (uuid)
    resignation_date: date
    last_working_day: date
    reason_category: str = Field(..., min_length=2)
    reason_remarks: Optional[str] = None
    admin_remarks: Optional[str] = None
    eligible_for_rehire: Optional[bool] = None


class ResignationUpdate(BaseModel):
    last_working_day: Optional[date] = None
    reason_category: Optional[str] = None
    reason_remarks: Optional[str] = None
    admin_remarks: Optional[str] = None
    eligible_for_rehire: Optional[bool] = None
    exit_checklist: Optional[dict[str, bool]] = None
    pending_salary: Optional[float] = Field(None, ge=0)
    leave_encashment: Optional[float] = Field(None, ge=0)
    deductions: Optional[float] = Field(None, ge=0)
    settlement_status: Optional[str] = None  # Pending | Paid
    settlement_paid_on: Optional[date] = None
