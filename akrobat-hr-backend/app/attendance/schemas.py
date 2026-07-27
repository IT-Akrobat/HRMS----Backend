from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CheckInRequest(BaseModel):

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    location_id: Optional[str] = None


class CheckOutRequest(BaseModel):

    latitude: Optional[float] = None

    longitude: Optional[float] = None


class RegularizationRequest(BaseModel):

    attendance_date: date

    requested_check_in: datetime

    requested_check_out: Optional[datetime] = None

    reason: str


class RegularizationDecisionRequest(BaseModel):

    status: str

    comments: Optional[str] = None


class AdminUpdateAttendanceRequest(BaseModel):

    check_in_time: Optional[datetime] = None

    check_out_time: Optional[datetime] = None

    status: Optional[str] = None


# ==========================================
# SITE VISITS (multi-location field staff — Inspection / Operation)
# ==========================================


class SiteVisitArriveRequest(BaseModel):

    location_id: str

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    notes: Optional[str] = None


class SiteVisitDepartRequest(BaseModel):

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    notes: Optional[str] = None
