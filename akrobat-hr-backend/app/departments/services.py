from fastapi import HTTPException

from app.core.database import supabase_admin


def _auto_department_code(name: str) -> str:
    """Short unique code from the name, e.g. "Human Resources" -> "HR",
    "Finance" -> "FIN". Falls back to a numbered suffix on a clash."""

    words = [w for w in "".join(c if c.isalnum() else " " for c in name).split() if w]
    base = (
        "".join(w[0] for w in words)[:4].upper()
        if len(words) > 1
        else (words[0][:3].upper() if words else "DEP")
    )

    existing = {
        (row.get("department_code") or "").upper()
        for row in (
            supabase_admin.table("departments").select("department_code").execute().data
            or []
        )
    }

    code, n = base, 2
    while code in existing:
        code = f"{base}{n}"
        n += 1

    return code


def create_department(data):

    try:

        name = " ".join((data.department_name or "").split())

        if len(name) < 2:
            raise HTTPException(status_code=400, detail="Department name is required.")

        clash = (
            supabase_admin.table("departments")
            .select("id")
            .ilike("department_name", name.replace("%", "\\%").replace("_", "\\_"))
            .execute()
        )

        if clash.data:
            raise HTTPException(
                status_code=409, detail="This department already exists."
            )

        code = (data.department_code or "").strip().upper() or _auto_department_code(
            name
        )

        response = (
            supabase_admin.table("departments")
            .insert({"department_name": name, "department_code": code})
            .execute()
        )

        return response.data[0]

    except HTTPException:

        raise

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
