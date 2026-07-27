from fastapi import HTTPException

from app.core.database import supabase_admin


def create_department(data):

    try:

        response = (
            supabase_admin.table("departments")
            .insert(
                {
                    "department_name": data.department_name,
                    "department_code": data.department_code,
                }
            )
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


def get_departments(department_id: str | None = None):

    try:

        query = supabase_admin.table("departments").select("*")

        # specific department
        if department_id:

            response = query.eq("id", department_id).single().execute()

            return response.data

        # all departments
        response = query.execute()

        return response.data

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))
