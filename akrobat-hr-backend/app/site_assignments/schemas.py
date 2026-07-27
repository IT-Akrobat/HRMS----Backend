from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class AssignSiteRequest(BaseModel):
    """Manager assigns ONE site to one or more explicitly-picked employees."""

    location_id: str

    employee_ids: List[str] = Field(..., min_length=1)

    assigned_from: Optional[date] = None

    assigned_to: Optional[date] = None

    notes: Optional[str] = None


class AssignSiteToTeamRequest(BaseModel):
    """Manager assigns ONE site to every one of their direct + indirect reports."""

    location_id: str

    assigned_from: Optional[date] = None

    assigned_to: Optional[date] = None

    notes: Optional[str] = None


class UpdateSiteAssignmentRequest(BaseModel):

    assigned_from: Optional[date] = None

    assigned_to: Optional[date] = None

    is_active: Optional[bool] = None

    notes: Optional[str] = None
