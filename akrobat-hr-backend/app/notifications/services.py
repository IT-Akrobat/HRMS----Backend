from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.exceptions import bad_request, internal_server_error, not_found
from app.core.logger import logger
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

# ---------------------------------------------------------------------------
# Backs NotificationsPage.jsx (src/components/common/Notificationpage.jsx),
# the shared Notifications screen used by every role. Contract:
#   GET  /notifications/my
#   PUT  /notifications/{id}/read
#   PUT  /notifications/my/read-all
#   DELETE /notifications/{id}
#
# Rows live in the "notifications" table (sql/001_schema.sql), keyed by
# user_id = employee_id. notify_employee() below is the fire-and-forget
# writer used by other modules (leaves, attendance, announcements, ...)
# to insert rows here.
# ---------------------------------------------------------------------------


def _resolve_employee_id(auth_user_id: str) -> str:
    employee_id = get_employee_id_for_auth_user(auth_user_id)
    if not employee_id:
        bad_request("No employee record is linked to this account.")
    return employee_id


# =========================
# LIST MY NOTIFICATIONS
# =========================


def get_my_notifications(auth_user_id: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        response = (
            supabase_admin.table("notifications")
            .select("*")
            .eq("user_id", employee_id)
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Notifications fetched successfully.",
            data=response.data or [],
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch notifications.")


# =========================
# MARK ONE NOTIFICATION READ
# =========================


def mark_notification_read(auth_user_id: str, notification_id: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        existing = (
            supabase_admin.table("notifications")
            .select("id")
            .eq("id", notification_id)
            .eq("user_id", employee_id)
            .maybe_single()
            .execute()
        )
        if not existing or not existing.data:
            not_found("Notification not found.")

        response = (
            supabase_admin.table("notifications")
            .update({"is_read": True})
            .eq("id", notification_id)
            .eq("user_id", employee_id)
            .execute()
        )

        row = response.data[0] if response.data else None

        return success_response(
            message="Notification marked as read.",
            data=row,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to mark notification as read.")


# =========================
# MARK ALL NOTIFICATIONS READ
# =========================


def mark_all_notifications_read(auth_user_id: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        response = (
            supabase_admin.table("notifications")
            .update({"is_read": True})
            .eq("user_id", employee_id)
            .eq("is_read", False)
            .execute()
        )

        return success_response(
            message="All notifications marked as read.",
            data=response.data or [],
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to mark all notifications as read.")


# =========================
# DELETE A NOTIFICATION
# =========================


def delete_notification(auth_user_id: str, notification_id: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        existing = (
            supabase_admin.table("notifications")
            .select("id")
            .eq("id", notification_id)
            .eq("user_id", employee_id)
            .maybe_single()
            .execute()
        )
        if not existing or not existing.data:
            not_found("Notification not found.")

        supabase_admin.table("notifications").delete().eq("id", notification_id).eq(
            "user_id", employee_id
        ).execute()

        return success_response(message="Notification deleted successfully.")

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to delete notification.")


# =========================
# INTERNAL: NOTIFY AN EMPLOYEE
# =========================


def notify_employee(
    employee_id: str | None,
    title: str,
    message: str,
    notification_type: str = "GENERAL",
):
    """
    Fire-and-forget notification insert for use *inside* other services
    (e.g. app/leaves/services.py notifying a manager of a new request, or
    an employee of an approval/rejection). Deliberately swallows errors --
    a broken notifications insert should never fail the action that
    triggered it -- and simply logs instead.
    """

    if not employee_id:
        return None

    try:
        response = (
            supabase_admin.table("notifications")
            .insert(
                {
                    "user_id": str(employee_id),
                    "title": title,
                    "message": message,
                    "notification_type": notification_type,
                }
            )
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Failed to send notification to {employee_id}: {e}")
        return None
