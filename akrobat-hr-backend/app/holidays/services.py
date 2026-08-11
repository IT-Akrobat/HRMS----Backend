from datetime import date, timedelta

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response


def _apply_sunday_shift(raw_date: date) -> tuple[date, bool]:
    """
    MOM's rule: a public holiday that falls on a Sunday is observed the
    following Monday. Returns (observed_date, was_shifted).
    """

    if raw_date.weekday() == 6:  # Monday=0 ... Sunday=6
        return raw_date + timedelta(days=1), True

    return raw_date, False


def create_holiday(data):

    try:

        response = (
            supabase_admin.table("holidays")
            .insert(
                {
                    "holiday_name": data.holiday_name,
                    "holiday_date": data.holiday_date,
                    "description": data.description,
                    "country": data.country,
                }
            )
            .execute()
        )

        return success_response(
            message="Holiday created successfully.", data=response.data[0]
        )

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


def bulk_import_holidays(items):
    """
    Populate `holidays` from a yearly source list (e.g. MOM's public
    holiday list). Each item's raw calendar date is Sunday-shifted here
    if needed -- holiday_date always ends up holding the actually
    OBSERVED date (what attendance/leave logic should treat as the day
    off), never the raw calendar date, per policy. raw_holiday_date is
    kept alongside it so Replacement Leave crediting can still detect a
    holiday that really fell on a Saturday.
    """

    try:
        rows = []

        for item in items:
            observed_date, was_shifted = _apply_sunday_shift(item.raw_holiday_date)

            rows.append(
                {
                    "holiday_name": item.holiday_name,
                    "holiday_date": str(observed_date),
                    "raw_holiday_date": str(item.raw_holiday_date),
                    "is_sunday_shifted": was_shifted,
                    "description": item.description,
                    "country": item.country,
                }
            )

        response = supabase_admin.table("holidays").insert(rows).execute()

        return success_response(
            message=f"{len(response.data or [])} holiday(s) imported.",
            data=response.data or [],
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def get_saturday_holidays(country: str = "SG", year: int | None = None):
    """
    Public holidays whose REAL calendar date (raw_holiday_date, or
    holiday_date if raw wasn't recorded) fell on a Saturday -- the
    candidates HR credits Replacement Leave for. See
    app/leaves/policy_services.py credit_replacement_leave().
    """

    query = supabase_admin.table("holidays").select("*").eq("country", country)

    if year:
        query = query.gte("holiday_date", f"{year}-01-01").lte(
            "holiday_date", f"{year}-12-31"
        )

    response = query.order("holiday_date").execute()

    saturday_holidays = [
        row
        for row in (response.data or [])
        if date.fromisoformat(
            row.get("raw_holiday_date") or row["holiday_date"]
        ).weekday()
        == 5  # Saturday
    ]

    return success_response(
        message="Saturday public holidays fetched successfully.",
        data=saturday_holidays,
    )


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

    return success_response(message="Holiday fetched successfully.", data=response.data)


def update_holiday(holiday_id: str, data: dict):

    response = (
        supabase_admin.table("holidays").update(data).eq("id", holiday_id).execute()
    )

    return success_response(
        message="Holiday updated successfully.", data=response.data[0]
    )


def delete_holiday(holiday_id: str):

    (supabase_admin.table("holidays").delete().eq("id", holiday_id).execute())

    return {"message": "Holiday deleted successfully"}
