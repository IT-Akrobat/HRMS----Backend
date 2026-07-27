from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response

from app.employee_project_assignments.schemas import (
    CreateAssignmentRequest,
    UpdateAssignmentRequest
)


# =========================
# CREATE ASSIGNMENT
# =========================

def create_assignment(
    data: CreateAssignmentRequest
):

    existing = supabase_admin.table(
        "employee_project_assignments"
    ).select(
        "id"
    ).eq(
        "employee_id",
        data.employee_id
    ).eq(
        "project_id",
        data.project_id
    ).eq(
        "is_active",
        True
    ).execute()

    if existing.data:

        raise HTTPException(
            status_code=400,
            detail="Employee is already assigned to this project"
        )

    response = supabase_admin.table(
        "employee_project_assignments"
    ).insert(
        {
            "employee_id": data.employee_id,
            "project_id": data.project_id,
            "assigned_from": data.assigned_from,
            "assigned_to": data.assigned_to,
            "remarks": data.remarks
        }
    ).execute()

    return success_response(
        message="Assignment created successfully.",
        data=response.data[0],
    )


# =========================
# GET ALL ASSIGNMENTS
# =========================

def get_assignments():

    response = supabase_admin.table(
        "employee_project_assignments"
    ).select(
        """
        *,
        employees(
            id,
            employee_id,
            full_name
        ),
        projects(
            id,
            project_name,
            project_code
        )
        """
    ).order(
        "created_at",
        desc=True
    ).execute()

    return success_response(
        message="Assignments fetched successfully.",
        data=response.data or [],
    )


# =========================
# GET ASSIGNMENT
# =========================

def get_assignment(
    assignment_id: str
):

    response = supabase_admin.table(
        "employee_project_assignments"
    ).select(
        """
        *,
        employees(
            id,
            employee_id,
            full_name
        ),
        projects(
            id,
            project_name,
            project_code
        )
        """
    ).eq(
        "id",
        assignment_id
    ).single().execute()

    if not response.data:

        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    return success_response(
        message="Assignment fetched successfully.",
        data=response.data,
    )


# =========================
# GET EMPLOYEE ASSIGNMENTS
# =========================

def get_employee_assignments(
    employee_id: str
):

    response = supabase_admin.table(
        "employee_project_assignments"
    ).select(
        """
        *,
        projects(
            id,
            project_name,
            project_code
        )
        """
    ).eq(
        "employee_id",
        employee_id
    ).execute()

    return success_response(
        message="Employee assignments fetched successfully.",
        data=response.data or [],
    )


# =========================
# GET PROJECT ASSIGNMENTS
# =========================

def get_project_assignments(
    project_id: str
):

    response = supabase_admin.table(
        "employee_project_assignments"
    ).select(
        """
        *,
        employees(
            id,
            employee_id,
            full_name
        )
        """
    ).eq(
        "project_id",
        project_id
    ).execute()

    return success_response(
        message="Project assignments fetched successfully.",
        data=response.data or [],
    )


# =========================
# UPDATE ASSIGNMENT
# =========================

def update_assignment(
    assignment_id: str,
    data: UpdateAssignmentRequest
):

    update_data = data.model_dump(
        exclude_unset=True
    )

    response = supabase_admin.table(
        "employee_project_assignments"
    ).update(
        update_data
    ).eq(
        "id",
        assignment_id
    ).execute()

    if not response.data:

        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    return success_response(
        message="Assignment updated successfully.",
        data=response.data[0],
    )


# =========================
# DELETE ASSIGNMENT
# =========================

def delete_assignment(
    assignment_id: str
):

    existing = supabase_admin.table(
        "employee_project_assignments"
    ).select(
        "id"
    ).eq(
        "id",
        assignment_id
    ).execute()

    if not existing.data:

        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    supabase_admin.table(
        "employee_project_assignments"
    ).delete().eq(
        "id",
        assignment_id
    ).execute()

    return success_response(
        message="Assignment deleted successfully.",
        data=None,
    )
