from datetime import date, datetime, time

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core import realtime
from app.core.exceptions import bad_request, internal_server_error, not_found
from app.core.logger import logger
from app.core.helpers.employee_helper import get_employee_id_for_auth_user
from app.core.email import send_email
from app.core.push import push_configured
from app.notification_preferences.services import get_preference
from app.push_subscriptions.services import send_push_to_employee

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
# CELEBRATIONS (BIRTHDAYS & WORK ANNIVERSARIES)
# =========================
#
# Backs the "Birthdays & work anniversaries" toggle. Same "no background
# scheduler exists in this backend" constraint as
# attendance.get_attendance_reminder_status() -- see that function's
# docstring -- so this is polled by the frontend instead of running on
# a cron. Gated entirely by the REQUESTING employee's own preference:
# if they've turned "celebrations" off, this always reports nothing.
#
# NOTE: relies on employees.date_of_birth existing. app/employees/services.py
# already reads/writes this column (My Profile edit), but no sql/*.sql
# migration in this repo actually creates it -- if it's missing on your
# database, birthdays silently won't show up (this function catches that
# and just skips birthdays, so it never crashes the poll). Add it with:
#   alter table employees add column if not exists date_of_birth date;
# Work anniversaries use the existing employees.joining_date column, which
# does exist, so those work without any migration.


def get_celebrations_status(auth_user_id: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        if not get_preference(employee_id, "celebrations"):
            return success_response(
                message="No celebrations due.", data={"celebrations": []}
            )

        today = date.today()

        try:
            employees = (
                supabase_admin.table("employees")
                .select("id, full_name, date_of_birth, joining_date")
                .eq("employment_status", "Active")
                .execute()
            )
            rows = employees.data or []
        except Exception as e:
            # Most likely date_of_birth doesn't exist on this database yet
            # -- degrade to "nothing due" rather than failing the poll.
            logger.error(f"Unable to check celebrations: {e}")
            return success_response(
                message="No celebrations due.", data={"celebrations": []}
            )

        def _as_date(value):
            if not value:
                return None
            return date.fromisoformat(value) if isinstance(value, str) else value

        celebrants = []
        for emp in rows:
            if emp.get("id") == employee_id:
                continue

            name = emp.get("full_name", "A teammate")

            dob = _as_date(emp.get("date_of_birth"))
            if dob and dob.month == today.month and dob.day == today.day:
                celebrants.append(
                    {
                        "message": f"Wish {name} a happy birthday today!",
                        "title": "Happy Birthday",
                    }
                )

            joined = _as_date(emp.get("joining_date"))
            if (
                joined
                and joined.month == today.month
                and joined.day == today.day
                and today.year > joined.year
            ):
                years = today.year - joined.year
                celebrants.append(
                    {
                        "message": (
                            f"{name} completes {years} year"
                            f"{'s' if years != 1 else ''} with the company today!"
                        ),
                        "title": "Work Anniversary",
                    }
                )

        if not celebrants:
            return success_response(
                message="No celebrations due.", data={"celebrations": []}
            )

        # Dedup per requesting employee per day, same idea as the
        # attendance reminder's ATTENDANCE_REMINDER dedup.
        day_start = datetime.combine(today, time(0, 0)).isoformat()
        already_sent = (
            supabase_admin.table("notifications")
            .select("message")
            .eq("user_id", employee_id)
            .eq("notification_type", "CELEBRATION")
            .gte("created_at", day_start)
            .execute()
        )
        already_sent_messages = {
            row.get("message") for row in (already_sent.data or [])
        }

        sent = []
        for c in celebrants:
            if c["message"] in already_sent_messages:
                continue
            notify_employee(
                employee_id,
                title=c["title"],
                message=c["message"],
                notification_type="CELEBRATION",
            )
            sent.append(c["message"])

        return success_response(
            message="Celebrations checked.",
            data={"celebrations": sent},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        return success_response(
            message="No celebrations due.", data={"celebrations": []}
        )


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

    row = None
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
        row = response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Failed to send notification to {employee_id}: {e}")
        return None

    # Push it to any open tab/socket for this employee right away -- see
    # app/core/realtime.py::broadcast_to_employee_threadsafe(). Safe to
    # call from the sync callers of notify_employee() (leaves, attendance,
    # etc). No-ops quietly if the employee has no socket open right now;
    # they'll still see it via GET /notifications/my on next load.
    try:
        realtime.broadcast_to_employee_threadsafe(
            str(employee_id), {"type": "notification", "notification": row}
        )
    except Exception as e:
        logger.error(f"Failed to push realtime notification to {employee_id}: {e}")

    # "Email notifications" toggle (Settings > Notifications) -- send a
    # copy of this same notification by email if the employee has opted
    # in. Defaults to on for anyone who's never saved preferences.
    # Best-effort: never lets a broken/unconfigured mailbox affect the
    # in-app notification, which has already been written above.
    try:
        if get_preference(employee_id, "email_notifications"):
            employee = (
                supabase_admin.table("employees")
                .select("email")
                .eq("id", employee_id)
                .maybe_single()
                .execute()
            )
            to_email = (employee.data or {}).get("email") if employee else None
            send_email(to_email, subject=title, body=message)
    except Exception as e:
        logger.error(f"Failed to send email copy to {employee_id}: {e}")

    # Real device push -- the "pops up like WhatsApp, even with the app
    # closed" behaviour. Same best-effort contract as the email copy
    # above: skipped silently if VAPID keys aren't configured yet
    # (push_configured() check avoids a pointless subscriptions lookup),
    # and any send failure here never affects the in-app notification
    # already written above.
    try:
        if push_configured():
            send_push_to_employee(employee_id, title=title, body=message)
    except Exception as e:
        logger.error(f"Failed to send push copy to {employee_id}: {e}")

    return row
