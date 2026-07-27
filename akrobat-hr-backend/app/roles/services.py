from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.messages import NOT_FOUND
from app.core.responses import success_response


# =========================
# GET ALL ROLES
# =========================


def get_roles():

    try:

        response = supabase_admin.table("roles").select("*").order("role_name").execute()

        return success_response(
            message="Roles fetched successfully",
            data=response.data or [],
        )

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# =========================
# GET ROLE BY ID
# =========================


def get_role_by_id(role_id: str):

    try:

        response = (
            supabase_admin.table("roles")
            .select("*")
            .eq("id", role_id)
            .maybe_single()
            .execute()
        )

        if not response or not response.data:
            raise HTTPException(status_code=404, detail=NOT_FOUND)

        return success_response(
            message="Role fetched successfully",
            data=response.data,
        )

    except HTTPException:
        raise

    except Exception:

        raise HTTPException(status_code=404, detail="Role not found")
