from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.core.rbac import require_permission

from app.site_assignments.schemas import (
    AssignSiteRequest,
    AssignSiteToTeamRequest,
    UpdateSiteAssignmentRequest,
)

from app.site_assignments.services import (
    assign_site_to_employees,
    assign_site_to_team,
    get_my_site_assignments,
    get_my_team_with_sites,
    get_employee_site_assignments,
    update_site_assignment,
    deactivate_site_assignment,
)

router = APIRouter(prefix="/site-assignments", tags=["Site Assignments"])


# ==========================================================================
# MANAGER — CREATE
# ==========================================================================


@router.post("/")
def assign_site(
    data: AssignSiteRequest, user=Depends(require_permission("MANAGE_SITE_ASSIGNMENTS"))
):
    """Assign one site to one or more explicitly-picked employees."""
    return assign_site_to_employees(user.id, data)


@router.post("/team")
def assign_site_team(
    data: AssignSiteToTeamRequest,
    user=Depends(require_permission("MANAGE_SITE_ASSIGNMENTS")),
):
    """Assign one site to the caller's ENTIRE team (direct + indirect reports)."""
    return assign_site_to_team(user.id, data)


# ==========================================================================
# MANAGER — TEAM PICKER (for the "Assign Site" page)
# ==========================================================================


@router.get("/my-team")
def my_team(user=Depends(require_permission("MANAGE_SITE_ASSIGNMENTS"))):
    """The caller's direct + indirect reports, each with their current assigned site(s)."""
    return get_my_team_with_sites(user.id)


# ==========================================================================
# SELF-SERVICE — MY CURRENT SITE (used by check-in / site-visit screens)
# ==========================================================================


@router.get("/my")
def my_assignments(user=Depends(get_current_user)):
    return get_my_site_assignments(user.id)


# ==========================================================================
# HISTORY FOR ONE EMPLOYEE
# ==========================================================================


@router.get("/employee/{employee_id}")
def employee_assignments(employee_id: str, user=Depends(get_current_user)):
    return get_employee_site_assignments(employee_id, auth_user_id=user.id)


# ==========================================================================
# UPDATE / REMOVE
# ==========================================================================


@router.put("/{assignment_id}")
def update_assignment(
    assignment_id: str,
    data: UpdateSiteAssignmentRequest,
    user=Depends(require_permission("MANAGE_SITE_ASSIGNMENTS")),
):
    return update_site_assignment(assignment_id, data, auth_user_id=user.id)


@router.delete("/{assignment_id}")
def remove_assignment(
    assignment_id: str,
    user=Depends(require_permission("MANAGE_SITE_ASSIGNMENTS")),
):
    return deactivate_site_assignment(assignment_id, auth_user_id=user.id)
