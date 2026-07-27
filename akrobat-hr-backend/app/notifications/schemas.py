from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class CreateNotificationRequest(BaseModel):

    employee_id: UUID

    title: str

    message: str

    notification_type: str = "GENERAL"


class UpdateNotificationRequest(BaseModel):

    title: Optional[str] = None

    message: Optional[str] = None

    notification_type: Optional[str] = None

    is_read: Optional[bool] = None


class NotificationResponse(BaseModel):

    id: UUID

    employee_id: UUID

    title: str

    message: str

    notification_type: str

    is_read: bool

    created_at: datetime
