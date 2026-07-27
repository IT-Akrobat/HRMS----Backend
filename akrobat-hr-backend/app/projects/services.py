from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.messages import PROJECT_CREATED, PROJECT_UPDATED, PROJECT_DELETED

from app.projects.schemas import (
    CreateProjectRequest,
    UpdateProjectRequest
)


# =========================
# CREATE PROJECT
# =========================

def create_project(
    data: CreateProjectRequest
):

    existing = supabase_admin.table(
        "projects"
    ).select(
        "id"
    ).eq(
        "project_code",
        data.project_code
    ).execute()

    if existing.data:

        raise HTTPException(
            status_code=400,
            detail="Project code already exists"
        )

    response = supabase_admin.table(
        "projects"
    ).insert(
        {
            "project_name": data.project_name,
            "project_code": data.project_code,
            "client_name": data.client_name,
            "location_id": data.location_id,
            "start_date": data.start_date,
            "end_date": data.end_date,
            "description": data.description,
            "status": data.status
        }
    ).execute()

    return success_response(
        message=PROJECT_CREATED,
        data=response.data[0],
    )


# =========================
# GET ALL PROJECTS
# =========================

def get_projects():

    response = supabase_admin.table(
        "projects"
    ).select(
        """
        *,
        locations(
            id,
            location_name,
            location_code
        )
        """
    ).order(
        "created_at",
        desc=True
    ).execute()

    return success_response(
        message="Projects fetched successfully.",
        data=response.data or [],
    )


# =========================
# GET PROJECT BY ID
# =========================

def get_project(
    project_id: str
):

    response = supabase_admin.table(
        "projects"
    ).select(
        """
        *,
        locations(
            id,
            location_name,
            location_code
        )
        """
    ).eq(
        "id",
        project_id
    ).single().execute()

    if not response.data:

        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return success_response(
        message="Project fetched successfully.",
        data=response.data,
    )


# =========================
# UPDATE PROJECT
# =========================

def update_project(
    project_id: str,
    data: UpdateProjectRequest
):

    update_data = data.model_dump(
        exclude_unset=True
    )

    if "project_code" in update_data:

        existing = supabase_admin.table(
            "projects"
        ).select(
            "id"
        ).eq(
            "project_code",
            update_data["project_code"]
        ).execute()

        if existing.data:

            for row in existing.data:

                if row["id"] != project_id:

                    raise HTTPException(
                        status_code=400,
                        detail="Project code already exists"
                    )

    response = supabase_admin.table(
        "projects"
    ).update(
        update_data
    ).eq(
        "id",
        project_id
    ).execute()

    if not response.data:

        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return success_response(
        message=PROJECT_UPDATED,
        data=response.data[0],
    )


# =========================
# DELETE PROJECT
# =========================

def delete_project(
    project_id: str
):

    existing = supabase_admin.table(
        "projects"
    ).select(
        "id"
    ).eq(
        "id",
        project_id
    ).execute()

    if not existing.data:

        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    supabase_admin.table(
        "projects"
    ).delete().eq(
        "id",
        project_id
    ).execute()

    return success_response(
        message=PROJECT_DELETED,
        data=None,
    )
