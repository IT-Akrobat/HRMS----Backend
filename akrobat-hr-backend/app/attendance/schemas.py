from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CheckInRequest(BaseModel):

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    location_id: Optional[str] = None

    # Already-resolved "Building, Area, City, State" string from the
    # client's own reverseGeocode() call (src/utils/Geocode.jsx) at the
    # moment of check-in -- i.e. exactly what the employee saw on screen.
    # Stored as-is (check_in_address) so every later viewer (audit logs,
    # reports) shows that same value instead of re-geocoding the raw
    # lat/lon independently, which can land on a different/worse result.
    # Best-effort: reverse geocoding can still be resolving or may have
    # failed client-side, so this is optional and never blocks check-in.
    address: Optional[str] = None


class CheckOutRequest(BaseModel):

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    location_id: Optional[str] = None

    # Same as CheckInRequest.address, but for check-out.
    address: Optional[str] = None


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


class SiteVisitPingRequest(BaseModel):
    """
    Fired every ~60s by the frontend while a site visit is open (see
    SiteVisitCard.jsx), so the employee's presence at the site can be
    verified continuously instead of only once at arrival. Unlike
    arrive/depart, latitude/longitude are required here — a ping with no
    coordinates can't verify anything, so the frontend simply skips
    sending one for that cycle if it doesn't have a fresh GPS fix yet.
    """

    latitude: float

    longitude: float


# ==========================================
# AD-HOC OUTDOOR / MEETING CHECK-IN (any employee with
# employees.outdoor_checkin_enabled = true -- see sql/030.sql)
# ==========================================


class OutdoorVisitArriveRequest(BaseModel):

    latitude: float

    longitude: float

    purpose: Optional[str] = None

    address_text: Optional[str] = None

    notes: Optional[str] = None


class OutdoorVisitDepartRequest(BaseModel):

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    notes: Optional[str] = None
