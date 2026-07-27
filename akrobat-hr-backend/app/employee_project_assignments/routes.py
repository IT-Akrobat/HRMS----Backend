from fastapi import APIRouter, Depends

from app.core.security import get_current_user

from app.employee_project_assignments.schemas import (
    CreateAssignmentRequest,
    UpdateAssignmentRequest,
)

from app.employee_project_assignments.services import (
    create_assignment,
    get_assignments,
    get_assignment,
    get_employee_assignments,
    get_project_assignments,
    update_assignment,
    delete_assignment,
)

router = APIRouter(
    prefix="/employee-project-assignments", tags=["Employee Project Assignments"]
)


# =========================
# CREATE ASSIGNMENT
# =========================


@router.post("/")
def create(data: CreateAssignmentRequest, user=Depends(get_current_user)):

    return create_assignment(data)


# =========================
# GET ALL ASSIGNMENTS
# =========================


@router.get("/")
def all_assignments(user=Depends(get_current_user)):

    return get_assignments()


# =========================
# GET ASSIGNMENT BY ID
# =========================


@router.get("/{assignment_id}")
def get_one(assignment_id: str, user=Depends(get_current_user)):

    return get_assignment(assignment_id)


# =========================
# GET EMPLOYEE ASSIGNMENTS
# =========================


@router.get("/employee/{employee_id}")
def employee_assignments(employee_id: str, user=Depends(get_current_user)):

    return get_employee_assignments(employee_id)


# =========================
# GET PROJECT ASSIGNMENTS
# =========================


@router.get("/project/{project_id}")
def project_assignments(project_id: str, user=Depends(get_current_user)):

    return get_project_assignments(project_id)


# =========================
# UPDATE ASSIGNMENT
# =========================


@router.put("/{assignment_id}")
def update(
    assignment_id: str, data: UpdateAssignmentRequest, user=Depends(get_current_user)
):

    return update_assignment(assignment_id, data)


# =========================
# DELETE ASSIGNMENT
# =========================


@router.delete("/{assignment_id}")
def delete(assignment_id: str, user=Depends(get_current_user)):

    return delete_assignment(assignment_id)
