from fastapi import HTTPException

from app.core.database import supabase_admin

# CREATE DESIGNATION


def create_designation(data):

    try:

        response = (
            supabase_admin.table("designations")
            .insert(
                {
                    "designation_name": data.designation_name,
                    "department_id": data.department_id,
                    "default_shift_id": data.default_shift_id,
                }
            )
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


# GET ALL / SPECIFIC DESIGNATION


def get_designations(designation_id: str | None = None):

    try:

        query = supabase_admin.table("designations").select("""
            *,
            departments(
                department_name
            ),
            shifts:default_shift_id(
                id,
                shift_name,
                start_time,
                end_time,
                working_hours
            )
            """)

        # specific

        if designation_id:

            response = query.eq("id", designation_id).single().execute()

            return response.data

        # all

        response = query.execute()

        return response.data

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# GET BY DEPARTMENT


def get_department_designations(department_id: str):

    try:

        response = (
            supabase_admin.table("designations")
            .select("*")
            .eq("department_id", department_id)
            .execute()
        )

        return response.data

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# UPDATE


def update_designation(designation_id: str, data: dict):

    try:

        response = (
            supabase_admin.table("designations")
            .update(data)
            .eq("id", designation_id)
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# DELETE


def delete_designation(designation_id: str):

    try:

        supabase_admin.table("designations").delete().eq("id", designation_id).execute()

        return {"message": "Designation deleted successfully"}

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))
