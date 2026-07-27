from pydantic import BaseModel
from datetime import date
from typing import Optional
from uuid import UUID


class CreateAnnouncementRequest(BaseModel):

    title: str

    description: str

    start_date: date

    end_date: date


class UpdateAnnouncementRequest(BaseModel):

    title: Optional[str] = None

    description: Optional[str] = None

    start_date: Optional[date] = None

    end_date: Optional[date] = None


class AnnouncementResponse(BaseModel):

    id: UUID

    title: str

    description: str

    start_date: date

    end_date: date

    created_by: UUID

    created_at: str
