from fastapi import HTTPException

from app.core.database import supabase_admin


def create_holiday(data):

    try:

        response = (
            supabase_admin.table("holidays")
            .insert(
                {
                    "holiday_name": data.holiday_name,
                    "holiday_date": data.holiday_date,
                    "description": data.description,
                }
            )
            .execute()
        )

        return success_response(message=EMPLOYEE_CREATED, data=response.data[0])[0]

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


def get_holidays(country=None):

    query = supabase_admin.table("holidays").select("*")

    if country:
        query = query.eq("country", country)

    response = query.order("holiday_date").execute()

    return {"success": True, "data": response.data}


def get_holiday(holiday_id: str):

    response = (
        supabase_admin.table("holidays")
        .select("*")
        .eq("id", holiday_id)
        .single()
        .execute()
    )

    return success_response(message=EMPLOYEE_CREATED, data=response.data[0])


def update_holiday(holiday_id: str, data: dict):

    response = (
        supabase_admin.table("holidays").update(data).eq("id", holiday_id).execute()
    )

    return success_response(message=EMPLOYEE_CREATED, data=response.data[0])[0]


def delete_holiday(holiday_id: str):

    (supabase_admin.table("holidays").delete().eq("id", holiday_id).execute())

    return {"message": "Holiday deleted successfully"}
