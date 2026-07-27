from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request

from app.core.rbac import require_permission
from app.core.permissions import require_role
from app.core.security import get_current_user

from app.employees.schemas import (
    EmployeeCreate,
    EmployeeSelfUpdate,
    EmployeeUpdate,
)

from app.employees.examples import CREATE_EMPLOYEE_EXAMPLES

from app.employees.services import (
    create_employee,
    get_employees,
    update_employee,
    update_my_profile,
    delete_employee,
    get_my_team_employees,
    preview_employee_code,
)

router = APIRouter(
    prefix="/employees",
    tags=["Employees"],
)


# ==========================================
# PREVIEW EMPLOYEE CODE
# ==========================================
#
# Declared ABOVE POST "/" / GET "/" on purpose so it's easy to find, and
# above GET "/{employee_id}"-style routes generally so "/preview-code"
# is never swallowed as a path param. Same SUPER ADMIN / HR gate as
# actually creating a user, since it exposes the department/designation
# sequence.


@router.get("/preview-code")
def preview_employee_code_route(
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):
    return preview_employee_code(
        department_id=department_id,
        designation_id=designation_id,
    )


# ==========================================
# CREATE EMPLOYEE
# ==========================================
#
# Who can call this: ONLY SUPER ADMIN or HR — a hard role check, not the
# data-driven CREATE_EMPLOYEE permission.
#
# The Owner (the one fixed SUPER ADMIN login bootstrapped via
# scripts/create_super_admin.py) uses this endpoint to create further
# SUPER ADMIN and HR accounts. Both SUPER ADMIN and HR can then create a
# user of ANY role — there is no per-role restriction beyond "caller
# must be SUPER ADMIN or HR". Which role gets created is just `role_id`
# in the body — there is no separate endpoint per role.
#
# Use the "Try it out" -> "Example" dropdown below in Swagger to load a
# ready-made payload for each role (department_id/designation_id are
# filled in with real ids from sql/011_team_leader_and_org_structure.sql
# and sql/001_schema.sql where possible). You still need to swap
# `role_id` for the real role id you want from GET /roles first — see
# the note at the top of each example.


@router.post("/")
def create_employee_route(
    request: Request,
    data: EmployeeCreate = Body(..., openapi_examples=CREATE_EMPLOYEE_EXAMPLES),
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):
    return create_employee(data, current_user=user, request=request)


# ==========================================
# GET EMPLOYEES
# ==========================================


@router.get("/")
def get_employees_route(
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    role_id: Optional[str] = Query(None),
    user=Depends(require_permission("VIEW_EMPLOYEE")),
):
    return get_employees(
        department_id=department_id,
        designation_id=designation_id,
        role_id=role_id,
    )


# ==========================================
# GET MY TEAM (Manager — direct + indirect reports only)
# ==========================================
#
# Unlike GET /employees/ (org-wide, gated only by the data-driven
# VIEW_EMPLOYEE permission that MANAGER also holds), this scopes the
# result to exactly the calling manager's own reporting line — same
# convention as GET /leaves/team and GET /attendance/team. Any signed-in
# user can call it; if they have no reports, they just get an empty list.


@router.get("/my-team")
def get_my_team_route(user=Depends(get_current_user)):
    return get_my_team_employees(user.id)


# ==========================================
# UPDATE MY OWN PERSONAL DETAILS ("My Profile")
# ==========================================
#
# Self-service: any signed-in user, no EDIT_EMPLOYEE permission needed --
# but EmployeeSelfUpdate only accepts phone + personal-detail fields
# (date_of_birth, gender, marital_status, nationality, blood_group,
# religion, address), never job/role fields. Declared ABOVE
# PUT /{employee_id} on purpose: FastAPI matches routes in declaration
# order, and "/me" would otherwise be swallowed by "/{employee_id}"
# with employee_id="me".


@router.put("/me")
def update_my_profile_route(
    data: EmployeeSelfUpdate,
    request: Request,
    user=Depends(get_current_user),
):
    return update_my_profile(auth_user_id=user.id, data=data, request=request)


# ==========================================
# UPDATE EMPLOYEE
# ==========================================


@router.put("/{employee_id}")
def update_employee_route(
    employee_id: str,
    data: EmployeeUpdate,
    request: Request,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    return update_employee(
        employee_id=employee_id,
        data=data,
        current_user=user,
        request=request,
    )


# ==========================================
# DELETE EMPLOYEE
# ==========================================


@router.delete("/{employee_id}")
def delete_employee_route(
    employee_id: str,
    request: Request,
    user=Depends(require_permission("DELETE_EMPLOYEE")),
):
    return delete_employee(employee_id, current_user=user, request=request)


# ==========================================
# GET EMPLOYEES BY DEPARTMENT
# ==========================================


@router.get("/department/{department_id}")
def get_department_employees(
    department_id: str,
    user=Depends(require_permission("VIEW_EMPLOYEE")),
):
    return get_employees(department_id=department_id)


# ==========================================
# GET EMPLOYEES BY DESIGNATION
# ==========================================


@router.get("/designation/{designation_id}")
def get_designation_employees(
    designation_id: str,
    user=Depends(require_permission("VIEW_EMPLOYEE")),
):
    return get_employees(designation_id=designation_id)
