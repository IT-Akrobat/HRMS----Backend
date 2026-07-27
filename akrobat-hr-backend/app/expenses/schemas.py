from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CreateExpenseRequest(BaseModel):

    expense_date: date

    category: str

    amount: Decimal

    description: Optional[str] = None

    receipt_url: Optional[str] = None


class UpdateExpenseRequest(BaseModel):

    expense_date: Optional[date] = None

    category: Optional[str] = None

    amount: Optional[Decimal] = None

    description: Optional[str] = None

    receipt_url: Optional[str] = None


class ExpenseApprovalRequest(BaseModel):

    remarks: Optional[str] = None


class ExpenseResponse(BaseModel):

    id: UUID

    employee_id: UUID

    expense_date: date

    category: str

    amount: Decimal

    description: Optional[str]

    receipt_url: Optional[str]

    status: str

    approved_by: Optional[UUID]

    approved_at: Optional[datetime]

    remarks: Optional[str]

    created_at: datetime

    updated_at: datetime
