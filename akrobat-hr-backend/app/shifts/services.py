from fastapi import HTTPException

from app.core.database import supabase_admin

# CREATE SHIFT


def create_shift(data):

    try:

        response = (
            supabase_admin.table("shifts")
            .insert(
                {
                    "shift_name": data.shift_name,
                    "start_time": data.start_time,
                    "end_time": data.end_time,
                    "working_hours": data.working_hours,
                    "break_duration": data.break_duration,
                    "grace_period": data.grace_period,
                    "status": data.status,
                }
            )
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


# GET ALL SHIFTS


def get_shifts():

    response = supabase_admin.table("shifts").select("*").execute()

    return response.data


# GET SPECIFIC SHIFT


def get_shift_by_id(shift_id: str):

    response = (
        supabase_admin.table("shifts").select("*").eq("id", shift_id).single().execute()
    )

    return response.data


# UPDATE SHIFT


def update_shift(shift_id: str, data: dict):

    response = supabase_admin.table("shifts").update(data).eq("id", shift_id).execute()

    return response.data[0]


# DELETE SHIFT


def delete_shift(shift_id: str):

    supabase_admin.table("shifts").delete().eq("id", shift_id).execute()

    return {"message": "Shift deleted successfully"}
