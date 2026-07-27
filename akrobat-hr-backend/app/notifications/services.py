from fastapi import HTTPException

import time

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.logger import logger

# ---------------------------------------------------------------------------
# NOTE ON SCHEMA
# ---------------------------------------------------------------------------
# sql/001_schema.sql defines `notifications.user_id` (not `employee_id`).
# Every notification in this app is actually scoped to an employee, so the
# API (schemas.py) keeps speaking in terms of `employee_id` for clarity —
# `_serialize()` below just maps the DB's `user_id` column to `employee_id`
# on the way out, and every write maps it back to `user_id` on the way in.
# ---------------------------------------------------------------------------


def _execute_with_retry(build_query, attempts: int = 2, delay: float = 0.15):
    """Runs a Supabase query, retrying once on the transient socket error
    seen on Windows dev machines ("[WinError 10035] A non-blocking socket
    operation could not be completed immediately" - WSAEWOULDBLOCK) when a
    burst of concurrent requests (e.g. the dashboard loading several
    widgets at once) hits supabase-py's shared httpx connection pool.
    `build_query` is a zero-arg callable that builds and executes the
    query fresh each attempt, since a Supabase query builder can't be
    re-executed once spent.
    """

    last_error = None
    for attempt in range(attempts):
        try:
            return build_query()
        except OSError as e:
            last_error = e
            if "10035" not in str(e) and "WOULDBLOCK" not in str(e).upper():
                raise
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last_error


def _serialize(row: dict | None) -> dict | None:
    if not row:
        return row
    row = dict(row)
    row["employee_id"] = row.pop("user_id", None)
    return row


def _serialize_many(rows) -> list:
    return [_serialize(r) for r in (rows or [])]


# =========================
# CREATE NOTIFICATION
# =========================


def create_notification(data):

    try:
        response = (
            supabase_admin.table("notifications")
            .insert(
                {
                    "user_id": str(data.employee_id),
                    "title": data.title,
                    "message": data.message,
                    "notification_type": data.notification_type,
                }
            )
            .execute()
        )

        return success_response(
            message="Notification created successfully.",
            data=_serialize(response.data[0]) if response.data else None,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# INTERNAL HELPER — used by other modules (leaves, overtime, attendance, ...)
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
    an employee of an approval/rejection). Deliberately swallows errors —
    a broken notifications insert should never fail the action that
    triggered it — and simply logs instead.
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
        logger.error(f"Failed to create notification for {employee_id}: {e}")
        return None


# =========================
# GET ALL NOTIFICATIONS (admin / debugging — company-wide)
# =========================


def get_notifications():

    try:
        response = (
            supabase_admin.table("notifications")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Notifications fetched successfully.",
            data=_serialize_many(response.data),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# GET EMPLOYEE NOTIFICATIONS
# =========================


def get_employee_notifications(employee_id: str):

    try:
        response = _execute_with_retry(
            lambda: supabase_admin.table("notifications")
            .select("*")
            .eq("user_id", employee_id)
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Notifications fetched successfully.",
            data=_serialize_many(response.data),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# GET SINGLE NOTIFICATION
# =========================


def get_notification(notification_id: str):

    try:
        response = (
            supabase_admin.table("notifications")
            .select("*")
            .eq("id", notification_id)
            .maybe_single()
            .execute()
        )

        if not response or not response.data:
            raise HTTPException(status_code=404, detail="Notification not found.")

        return success_response(
            message="Notification fetched successfully.",
            data=_serialize(response.data),
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# =========================
# UPDATE NOTIFICATION
# =========================


def update_notification(notification_id: str, data: dict):

    try:
        response = (
            supabase_admin.table("notifications")
            .update(data)
            .eq("id", notification_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Notification not found.")

        return success_response(
            message="Notification updated successfully.",
            data=_serialize(response.data[0]),
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# MARK AS READ
# =========================


def mark_as_read(notification_id: str):

    try:
        response = (
            supabase_admin.table("notifications")
            .update({"is_read": True})
            .eq("id", notification_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Notification not found.")

        return success_response(
            message="Notification marked as read.",
            data=_serialize(response.data[0]),
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# MARK ALL AS READ (for one employee)
# =========================


def mark_all_as_read(employee_id: str):

    try:
        response = (
            supabase_admin.table("notifications")
            .update({"is_read": True})
            .eq("user_id", employee_id)
            .eq("is_read", False)
            .execute()
        )

        return success_response(
            message="All notifications marked as read.",
            data=_serialize_many(response.data),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# DELETE NOTIFICATION
# =========================


def delete_notification(notification_id: str):

    try:
        supabase_admin.table("notifications").delete().eq(
            "id", notification_id
        ).execute()

        return success_response(message="Notification deleted successfully.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# BROADCAST NOTIFICATION (to every employee)
# =========================


def broadcast_notification(data):

    try:
        employees = supabase_admin.table("employees").select("id").execute()

        notifications = [
            {
                "user_id": employee["id"],
                "title": data.title,
                "message": data.message,
                "notification_type": data.notification_type,
            }
            for employee in (employees.data or [])
        ]

        if not notifications:
            return success_response(message="No employees to notify.", data=[])

        response = supabase_admin.table("notifications").insert(notifications).execute()

        return success_response(
            message="Notification broadcast successfully.",
            data=_serialize_many(response.data),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
