"""
Works out which timezone an attendance record belongs to.

Order (first match wins):
  1. GPS of the check-in (or check-out) -> Singapore / India
  2. employees.work_location mentioning Singapore / India
  3. the company timezone from Settings

Nationality is deliberately NOT used: it says nothing about where the
person physically worked that day.
"""

import re
from typing import Optional
from zoneinfo import ZoneInfo

# (min_lat, max_lat, min_lon, max_lon, timezone). Singapore is checked
# first; the boxes don't overlap.
_REGIONS = (
    (1.15, 1.50, 103.55, 104.10, "Asia/Singapore"),
    (6.0, 37.5, 68.0, 97.5, "Asia/Kolkata"),
)

_LOCATION_HINTS = (
    (re.compile(r"singapore|singaporean", re.I), "Asia/Singapore"),
    (re.compile(r"india|indian", re.I), "Asia/Kolkata"),
)


def timezone_from_coordinates(lat, lon) -> Optional[ZoneInfo]:
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    for min_lat, max_lat, min_lon, max_lon, name in _REGIONS:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return ZoneInfo(name)
    return None


def timezone_from_work_location(work_location) -> Optional[ZoneInfo]:
    text = str(work_location or "")
    for pattern, name in _LOCATION_HINTS:
        if pattern.search(text):
            return ZoneInfo(name)
    return None


def resolve_record_timezone(record, work_location, fallback: ZoneInfo) -> ZoneInfo:
    """record = an attendance row (dict) that may carry check-in/out GPS."""
    record = record or {}
    for lat_key, lon_key in (
        ("check_in_latitude", "check_in_longitude"),
        ("check_out_latitude", "check_out_longitude"),
    ):
        zone = timezone_from_coordinates(record.get(lat_key), record.get(lon_key))
        if zone:
            return zone
    return timezone_from_work_location(work_location) or fallback
