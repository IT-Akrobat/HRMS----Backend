from pydantic import BaseModel
from typing import Optional


# All seven toggles from Settings.jsx's "Notifications" tab. Every field
# is optional on the update payload so the frontend can PUT the whole
# form every time it saves without needing partial-patch semantics.
class UpdateNotificationPreferencesRequest(BaseModel):

    email_notifications: Optional[bool] = None

    leave_updates: Optional[bool] = None

    announcements: Optional[bool] = None

    celebrations: Optional[bool] = None

    attendance_reminders: Optional[bool] = None

    checkout_reminders: Optional[bool] = None

    holiday_reminders: Optional[bool] = None


class NotificationPreferencesResponse(BaseModel):

    employee_id: str

    email_notifications: bool

    leave_updates: bool

    announcements: bool

    celebrations: bool

    attendance_reminders: bool

    checkout_reminders: bool

    holiday_reminders: bool
