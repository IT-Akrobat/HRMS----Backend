from datetime import date

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response

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

        return success_response(
            "Announcement created successfully",
            data=_row_to_api(response.data[0]),
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

        today = str(date.today())

        response = (
            supabase_admin.table("announcements")
            .select("*")
            .lte("start_date", today)
            .gte("end_date", today)
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
