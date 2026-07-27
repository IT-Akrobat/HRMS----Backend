from typing import Optional

from pydantic import BaseModel


class CreateDesignationRequest(BaseModel):

    designation_name: str

    department_id: str

    # Working hours a new employee in this designation should default to
    # (Office / Operation Site / Inspection Site / Work Shop — see
    # sql/014_designation_shifts_and_site_visits.sql). Optional: HR can
    # still hand-pick a shift per employee at creation time either way.
    default_shift_id: Optional[str] = None
