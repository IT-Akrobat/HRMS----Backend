from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.exceptions import bad_request, internal_server_error
from app.core.logger import logger
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

# ---------------------------------------------------------------------------
# Backs the Notifications tab in Settings.jsx (Account / Security /
# Notifications / Preferences). Previously these five toggles only ever
# lived in localStorage (see Settings.jsx saveNotifications()) -- this
# module is the real store so:
#   1. Preferences follow the employee across devices/browsers instead of
#      being stuck on whichever machine they last clicked "Save" on.
#   2. Other parts of the backend (see attendance.get_attendance_reminder_status,
#      which reads this table directly) can actually respect the toggle --
#      "Attendance reminders" being OFF here is what stops that reminder
#      from firing at all.
#
# One row per employee, keyed by employee_id (sql/020_notification_preferences.sql).
# Defaults mirror Settings.jsx's NOTIF_DEFAULTS exactly, so a first-time
# GET (no row yet) returns the same values the UI already showed by
# default when this was localStorage-only.
# ---------------------------------------------------------------------------

DEFAULTS = {
    "email_notifications": True,
    "leave_updates": True,
    "announcements": True,
    "celebrations": True,
    "attendance_reminders": False,
}


def _resolve_employee_id(auth_user_id: str) -> str:
    employee_id = get_employee_id_for_auth_user(auth_user_id)
    if not employee_id:
        bad_request("No employee record is linked to this account.")
    return employee_id


# =========================
# GET MY PREFERENCES
# =========================


def get_my_preferences(auth_user_id: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        response = (
            supabase_admin.table("notification_preferences")
            .select("*")
            .eq("employee_id", employee_id)
            .maybe_single()
            .execute()
        )

        if response and response.data:
            row = response.data
        else:
            # No row yet -- this employee has never saved preferences
            # before. Return the same defaults the frontend used to
            # assume locally, without writing anything until they
            # actually hit Save.
            row = {"employee_id": employee_id, **DEFAULTS}

        return success_response(
            message="Notification preferences fetched successfully.",
            data=row,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch notification preferences.")


# =========================
# UPDATE MY PREFERENCES
# =========================


def update_my_preferences(auth_user_id: str, updates: dict):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        if not updates:
            return get_my_preferences(auth_user_id)

        payload = {"employee_id": employee_id, **updates}

        response = (
            supabase_admin.table("notification_preferences")
            .upsert(payload, on_conflict="employee_id")
            .execute()
        )

        row = response.data[0] if response.data else payload

        return success_response(
            message="Notification preferences updated successfully.",
            data=row,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update notification preferences.")
