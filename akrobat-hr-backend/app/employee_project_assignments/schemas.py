from datetime import date
from typing import Optional

from pydantic import BaseModel


class CreateAssignmentRequest(BaseModel):

    employee_id: str

    project_id: str

    assigned_from: date

    assigned_to: Optional[date] = None

    remarks: Optional[str] = None


class UpdateAssignmentRequest(BaseModel):

    project_id: Optional[str] = None

    assigned_from: Optional[date] = None

    assigned_to: Optional[date] = None

    is_active: Optional[bool] = None

    remarks: Optional[str] = None
