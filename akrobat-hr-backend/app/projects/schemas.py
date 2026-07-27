from datetime import date
from typing import Optional

from pydantic import BaseModel

# =========================
# CREATE PROJECT
# =========================


class CreateProjectRequest(BaseModel):

    project_name: str

    project_code: str

    client_name: Optional[str] = None

    location_id: Optional[str] = None

    start_date: Optional[date] = None

    end_date: Optional[date] = None

    description: Optional[str] = None

    status: Optional[str] = "ACTIVE"


# =========================
# UPDATE PROJECT
# =========================


class UpdateProjectRequest(BaseModel):

    project_name: Optional[str] = None

    project_code: Optional[str] = None

    client_name: Optional[str] = None

    location_id: Optional[str] = None

    start_date: Optional[date] = None

    end_date: Optional[date] = None

    description: Optional[str] = None

    status: Optional[str] = None
