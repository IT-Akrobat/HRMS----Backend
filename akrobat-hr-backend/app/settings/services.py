from fastapi import HTTPException

from app.core.database import supabase_admin

# =========================
# CREATE SETTINGS
# =========================


def create_settings(data):

    try:

        existing = supabase_admin.table("settings").select("id").execute()

        if existing.data:

            raise HTTPException(status_code=400, detail="Settings already exist")

        response = (
            supabase_admin.table("settings")
            .insert(
                {
                    "company_name": data.company_name,
                    "company_email": data.company_email,
                    "company_phone": data.company_phone,
                    "company_address": data.company_address,
                    "company_logo": data.company_logo,
                    "office_start_time": str(data.office_start_time),
                    "office_end_time": str(data.office_end_time),
                    "default_shift_id": (
                        str(data.default_shift_id) if data.default_shift_id else None
                    ),
                    "currency": data.currency,
                    "timezone": data.timezone,
                }
            )
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# GET SETTINGS
# =========================


def get_settings():

    try:

        response = supabase_admin.table("settings").select("""
            *,
            shifts(
                id,
                shift_name
            )
            """).limit(1).execute()

        if response.data:

            return response.data[0]

        return {}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# UPDATE SETTINGS
# =========================


def update_settings(data: dict):

    try:

        settings = supabase_admin.table("settings").select("id").limit(1).execute()

        if not settings.data:

            raise HTTPException(status_code=404, detail="Settings not found")

        response = (
            supabase_admin.table("settings")
            .update(data)
            .eq("id", settings.data[0]["id"])
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# DELETE SETTINGS
# =========================


def delete_settings():

    try:

        settings = supabase_admin.table("settings").select("id").limit(1).execute()

        if not settings.data:

            raise HTTPException(status_code=404, detail="Settings not found")

        supabase_admin.table("settings").delete().eq(
            "id", settings.data[0]["id"]
        ).execute()

        return {"message": "Settings deleted successfully"}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))
