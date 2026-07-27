from pydantic import BaseModel
from typing import Optional
from datetime import time
from uuid import UUID


class SettingsRequest(BaseModel):

    company_name: str

    company_email: str

    company_phone: str

    company_address: str

    company_logo: Optional[str] = None

    office_start_time: time

    office_end_time: time

    default_shift_id: Optional[UUID] = None

    currency: str = "SGD"

    timezone: str = "Asia/Singapore"


class UpdateSettingsRequest(BaseModel):

    company_name: Optional[str] = None

    company_email: Optional[str] = None

    company_phone: Optional[str] = None

    company_address: Optional[str] = None

    company_logo: Optional[str] = None

    office_start_time: Optional[time] = None

    office_end_time: Optional[time] = None

    default_shift_id: Optional[UUID] = None

    currency: Optional[str] = None

    timezone: Optional[str] = None
