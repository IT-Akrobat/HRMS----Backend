from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CreateAuditLogRequest(BaseModel):

    action: str

    module: str

    record_id: Optional[UUID] = None

    description: Optional[str] = None

    ip_address: Optional[str] = None

    user_agent: Optional[str] = None


class AuditLogResponse(BaseModel):

    id: UUID

    employee_id: Optional[UUID]

    action: str

    module: str

    record_id: Optional[UUID]

    description: Optional[str]

    ip_address: Optional[str]

    user_agent: Optional[str]

    created_at: datetime
