from datetime import date
from typing import Optional

from pydantic import BaseModel


class CreateDocumentRequest(BaseModel):

    employee_id: str

    document_name: str

    document_type: str

    file_url: str

    expiry_date: Optional[date] = None

    remarks: Optional[str] = None


class UpdateDocumentRequest(BaseModel):

    document_name: Optional[str] = None

    document_type: Optional[str] = None

    file_url: Optional[str] = None

    expiry_date: Optional[date] = None

    remarks: Optional[str] = None
