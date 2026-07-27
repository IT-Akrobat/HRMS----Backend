from datetime import date

from fastapi import HTTPException

from app.core.database import supabase_admin

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
                    "description": data.description,
                    "start_date": data.start_date,
                    "end_date": data.end_date,
                    "created_by": user_id,
                }
            )
            .execute()
        )

        return response.data[0]

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

        return response.data

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

        return response.data

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

        return response.data

    except Exception as e:

        raise HTTPException(status_code=404, detail=str(e))


# =========================
# UPDATE
# =========================


def update_announcement(announcement_id: str, data: dict):

    try:

        response = (
            supabase_admin.table("announcements")
            .update(data)
            .eq("id", announcement_id)
            .execute()
        )

        return response.data[0]

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
