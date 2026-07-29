from typing import Optional

from pydantic import BaseModel, Field


class UpdateAccessControlSettings(BaseModel):
    """
    Every field optional -- the frontend sends only the fields the admin
    actually changed (same partial-update pattern as
    app/settings/schemas.py::UpdateSettingsRequest).
    """

    require_2fa: Optional[bool] = None
    session_timeout_minutes: Optional[int] = Field(None, ge=5, le=1440)

    password_min_length: Optional[int] = Field(None, ge=6, le=32)
    password_require_complexity: Optional[bool] = None
    password_expiry_days: Optional[int] = Field(None, ge=0, le=365)

    lockout_attempts: Optional[int] = Field(None, ge=3, le=10)
    lockout_duration_minutes: Optional[int] = Field(None, ge=1, le=1440)

    restrict_to_office: Optional[bool] = None
    allowed_ip_ranges: Optional[list[str]] = None
