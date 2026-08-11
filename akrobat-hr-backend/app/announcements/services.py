from datetime import date, timedelta

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.logger import logger
from app.notifications.services import notify_employee
from app.notification_preferences.services import get_preference

# Every other module in this app returns { success, message, data } (see
# app/core/responses.py -> success_response, and app/holidays/services.py
# for the same pattern) and the frontend reads announcements the same way
# everywhere (`res.data || []` — see employee/manager/hr-admin/super-admin
# Dashboard.jsx). This module used to return the raw list/row instead of
# that envelope, so `res.data` was always undefined on the frontend and
# every dashboard silently rendered "No active announcements." regardless
# of what was actually in the table. Wrapping with success_response fixes
# that without touching the frontend or the DB schema.

# The announcements table (see sql/001_schema.sql) stores the body text in
# a column called "message", but the API contract (schemas.py,
# AnnouncementResponse) and the frontend both use "description". Insert/
# update with a "description" key fails with PGRST204 ("Could not find the
# 'description' column"), so translate at the boundary instead of touching
# the DB schema or the public API shape.


def _row_to_api(row: dict) -> dict:
    if row is None:
        return row
    if "message" in row:
        row = {**row, "description": row.pop("message")}
    return row


# =========================
# CREATE ANNOUNCEMENT
# =========================


def create_announcement(data, user_id: str):

    try:

        response = (
            supabase_admin.table("announcements")
            .insert(
                {
                    "title": data.title,
                    "message": data.description,
                    # supabase-py builds the request body with plain
                    # json.dumps(), which doesn't know how to serialize
                    # Python date objects (unlike FastAPI's own response
                    # encoder) — send ISO strings ("YYYY-MM-DD") instead.
                    "start_date": data.start_date.isoformat(),
                    "end_date": data.end_date.isoformat(),
                    "created_by": user_id,
                }
            )
            .execute()
        )

        created = response.data[0]

        # Best-effort fan-out: notify every active employee that a new
        # company-wide announcement went out, EXCEPT anyone who has
        # switched "Announcements" off under Settings > Notifications
        # (get_preference() defaults to on for anyone who's never saved
        # preferences, matching NOTIF_DEFAULTS). Deliberately wrapped so a
        # broken notify pass never fails the announcement creation itself
        # -- same pattern as every other notify_employee() call site.
        try:
            employees = (
                supabase_admin.table("employees")
                .select("id")
                .eq("employment_status", "Active")
                .execute()
            )
            for row in employees.data or []:
                employee_id = row.get("id")
                if not employee_id or employee_id == user_id:
                    continue
                if not get_preference(employee_id, "announcements"):
                    continue
                notify_employee(
                    employee_id,
                    title=data.title,
                    message=data.description,
                    notification_type="ANNOUNCEMENT",
                )
        except Exception as e:
            logger.error(f"Failed to fan out announcement notifications: {e}")

        return success_response(
            "Announcement created successfully",
            data=_row_to_api(created),
        )

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# GET ALL ANNOUNCEMENTS
# =========================


def get_announcements():

    try:

        response = supabase_admin.table("announcements").select("""
            *,
            employees(
                full_name,
                employee_id
            )
            """).order("created_at", desc=True).execute()

        return success_response(
            "Announcements fetched successfully",
            data=[_row_to_api(row) for row in response.data],
        )

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# ACTIVE ANNOUNCEMENTS
# =========================


def get_active_announcements():

    try:

        today = date.today()

        # "Active" here means still current OR ended within the last week —
        # Employee/Manager/HR (the only callers of this endpoint; Super
        # Admin uses GET /announcements/ instead, see routes.py) should
        # keep seeing an announcement for a 7-day grace period after its
        # end_date before it drops off their dashboard, instead of it
        # disappearing the instant end_date passes.
        cutoff = str(today - timedelta(days=7))
        today_str = str(today)

        response = (
            supabase_admin.table("announcements")
            .select("*")
            .lte("start_date", today_str)
            .gte("end_date", cutoff)
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            "Active announcements fetched successfully",
            data=[_row_to_api(row) for row in response.data],
        )

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# GET ONE
# =========================


def get_announcement(announcement_id: str):

    try:

        response = (
            supabase_admin.table("announcements")
            .select("*")
            .eq("id", announcement_id)
            .single()
            .execute()
        )

        return success_response(
            "Announcement fetched successfully",
            data=_row_to_api(response.data),
        )

    except Exception as e:

        raise HTTPException(status_code=404, detail=str(e))


# =========================
# UPDATE
# =========================


def update_announcement(announcement_id: str, data: dict):

    try:

        # data comes from UpdateAnnouncementRequest.model_dump(), so
        # start_date/end_date (when present) are still Python date
        # objects — same non-serializable issue as create_announcement.
        if isinstance(data.get("start_date"), date):
            data["start_date"] = data["start_date"].isoformat()

        if isinstance(data.get("end_date"), date):
            data["end_date"] = data["end_date"].isoformat()

        # Same "message" vs "description" column mismatch as create.
        if "description" in data:
            data["message"] = data.pop("description")

        response = (
            supabase_admin.table("announcements")
            .update(data)
            .eq("id", announcement_id)
            .execute()
        )

        return success_response(
            "Announcement updated successfully",
            data=_row_to_api(response.data[0]),
        )

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# DELETE
# =========================


def delete_announcement(announcement_id: str):

    try:

        supabase_admin.table("announcements").delete().eq(
            "id", announcement_id
        ).execute()

        return {"message": "Announcement deleted successfully"}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))
