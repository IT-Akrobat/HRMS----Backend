from datetime import date
from typing import Optional

from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, forbidden, not_found, internal_server_error
from app.core.rbac import has_permission
from app.core.constants import ADMIN, HR
from app.core.helpers.employee_helper import (
    get_employee_id_for_auth_user,
    get_all_report_ids,
    is_manager_of,
    is_field_employee,
    get_field_employee_ids,
)
from app.notifications.services import notify_employee

from app.site_assignments.schemas import (
    AssignSiteRequest,
    AssignSiteToTeamRequest,
    UpdateSiteAssignmentRequest,
)

SITE_ASSIGNMENT_SELECT = """
    *,
    employees!employee_site_assignments_employee_id_fkey(
        id, employee_id, full_name
    ),
    locations(
        id, location_name, location_code, address, latitude, longitude, radius
    )
"""


# ==========================================================================
# INTERNAL HELPERS
# ==========================================================================


def _can_manage_target(
    auth_user_id: str, manager_employee_id: Optional[str], target_employee_id: str
) -> bool:
    """
    HR / HR ADMIN / HR EXECUTIVE / SUPER ADMIN can assign a site to anyone.
    Everyone else (MANAGER / TEAM LEADER / OPERATIONS MANAGER — anyone
    holding MANAGE_SITE_ASSIGNMENTS) may only target their own direct or
    indirect reports.
    """

    if has_permission(auth_user_id, "VIEW_ALL_ATTENDANCE"):
        return True  # HR-tier roles already get this broad permission elsewhere

    if not manager_employee_id:
        return False

    return is_manager_of(manager_employee_id, target_employee_id)


def _validate_location(location_id: str) -> dict:
    response = (
        supabase_admin.table("locations")
        .select("*")
        .eq("id", location_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        not_found("Site (location) not found.")

    return response.data


def _require_field_employee(employee_id: str, full_name: Optional[str] = None) -> None:
    """
    Site assignment (and therefore the multi-site check-in flow) only
    applies to Inspection/Operation field staff — everyone else works a
    single fixed location and has no use for it. Raises 400 if the
    target employee's department isn't Inspection/Operation.
    """

    if not is_field_employee(employee_id):
        who = full_name or employee_id
        bad_request(
            f"{who} is not in an Inspection/Operation role — only field staff "
            "in those departments can be assigned a site."
        )


def _validate_employee(employee_id: str) -> dict:
    response = (
        supabase_admin.table("employees")
        .select("id, employee_id, full_name")
        .eq("id", employee_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        not_found(f"Employee {employee_id} not found.")

    return response.data


def _assign_location_to_employees(
    location: dict,
    employee_ids: list[str],
    assigned_by_employee_id: Optional[str],
    assigned_from: Optional[date],
    assigned_to: Optional[date],
    notes: Optional[str],
) -> list[dict]:
    """
    For each employee: deactivate whatever active assignment(s) they have
    (a site assignment replaces the previous one — an employee's "current
    site" is meant to be unambiguous for check-in purposes), then insert
    the new active row. Re-assigning the SAME site they already have is a
    no-op (just refreshes dates/notes) rather than a duplicate row.
    """

    created_or_updated: list[dict] = []

    for employee_id in employee_ids:

        existing_same_site = (
            supabase_admin.table("employee_site_assignments")
            .select("id")
            .eq("employee_id", employee_id)
            .eq("location_id", location["id"])
            .eq("is_active", True)
            .execute()
        )

        # Deactivate every OTHER currently-active assignment for this employee.
        supabase_admin.table("employee_site_assignments").update(
            {"is_active": False}
        ).eq("employee_id", employee_id).eq("is_active", True).neq(
            "location_id", location["id"]
        ).execute()

        if existing_same_site.data:
            assignment_id = existing_same_site.data[0]["id"]
            update_payload = {"notes": notes} if notes is not None else {}
            if assigned_to is not None:
                update_payload["assigned_to"] = assigned_to.isoformat()
            if update_payload:
                supabase_admin.table("employee_site_assignments").update(
                    update_payload
                ).eq("id", assignment_id).execute()
            row = (
                supabase_admin.table("employee_site_assignments")
                .select(SITE_ASSIGNMENT_SELECT)
                .eq("id", assignment_id)
                .single()
                .execute()
            )
            created_or_updated.append(row.data)
            continue

        payload = {
            "employee_id": employee_id,
            "location_id": location["id"],
            "assigned_by": assigned_by_employee_id,
            "assigned_from": (assigned_from or date.today()).isoformat(),
            "assigned_to": assigned_to.isoformat() if assigned_to else None,
            "is_active": True,
            "notes": notes,
        }

        inserted = (
            supabase_admin.table("employee_site_assignments").insert(payload).execute()
        )

        row = (
            supabase_admin.table("employee_site_assignments")
            .select(SITE_ASSIGNMENT_SELECT)
            .eq("id", inserted.data[0]["id"])
            .single()
            .execute()
        )
        created_or_updated.append(row.data)

        try:
            notify_employee(
                employee_id,
                title="Site Assignment",
                message=f"You have been assigned to {location.get('location_name', 'a new site')}.",
                notification_type="ATTENDANCE",
            )
        except Exception as e:
            logger.error(f"Failed to send site assignment notification: {e}")

    return created_or_updated


# ==========================================================================
# CREATE — SINGLE / MULTIPLE EXPLICIT EMPLOYEES
# ==========================================================================


def assign_site_to_employees(auth_user_id: str, data: AssignSiteRequest):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        location = _validate_location(data.location_id)

        for employee_id in data.employee_ids:
            employee = _validate_employee(employee_id)

            if not _can_manage_target(auth_user_id, manager_employee_id, employee_id):
                forbidden(
                    f"You can only assign a site to your own team members ({employee_id} is not one of your reports)."
                )

            _require_field_employee(employee_id, employee.get("full_name"))

        results = _assign_location_to_employees(
            location=location,
            employee_ids=data.employee_ids,
            assigned_by_employee_id=manager_employee_id,
            assigned_from=data.assigned_from,
            assigned_to=data.assigned_to,
            notes=data.notes,
        )

        return success_response(
            message=f"Site assigned to {len(results)} employee(s) successfully.",
            data=results,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to assign site.")


# ==========================================================================
# CREATE — WHOLE TEAM (direct + indirect reports of the caller)
# ==========================================================================


def assign_site_to_team(auth_user_id: str, data: AssignSiteToTeamRequest):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            forbidden("No employee profile is linked to this account.")

        report_ids = get_all_report_ids(manager_employee_id)

        if not report_ids:
            bad_request("You don't have any team members to assign a site to.")

        # "Whole team" only ever means the Inspection/Operation field staff
        # on the team — everyone else works a single fixed location and
        # isn't part of the multi-site check-in flow, so they're silently
        # excluded rather than blocking the whole action.
        field_ids = get_field_employee_ids()
        report_ids = [rid for rid in report_ids if rid in field_ids]

        if not report_ids:
            bad_request(
                "None of your team members are in an Inspection/Operation role — "
                "site assignment only applies to field staff in those departments."
            )

        location = _validate_location(data.location_id)

        results = _assign_location_to_employees(
            location=location,
            employee_ids=report_ids,
            assigned_by_employee_id=manager_employee_id,
            assigned_from=data.assigned_from,
            assigned_to=data.assigned_to,
            notes=data.notes,
        )

        return success_response(
            message=f"Site assigned to your whole team ({len(results)} employee(s)) successfully.",
            data=results,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to assign site to team.")


# ==========================================================================
# READ — MY CURRENT ASSIGNMENT(S) (self-service, for check-in screens)
# ==========================================================================


def get_my_site_assignments(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(
                message="Site assignments fetched successfully.", data=[]
            )

        response = (
            supabase_admin.table("employee_site_assignments")
            .select(SITE_ASSIGNMENT_SELECT)
            .eq("employee_id", employee_id)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Site assignments fetched successfully.", data=response.data or []
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch your site assignments.")


# ==========================================================================
# READ — MY TEAM, WITH THEIR CURRENT SITE (for the "Assign Site" page)
# ==========================================================================


def get_my_team_with_sites(auth_user_id: str):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(message="Team fetched successfully.", data=[])

        report_ids = get_all_report_ids(manager_employee_id)

        if not report_ids:
            return success_response(message="Team fetched successfully.", data=[])

        # This list feeds the "Assign Site" picker — site assignment (and
        # the multi-site check-in flow it unlocks) only makes sense for
        # Inspection/Operation field staff, so reports from every other
        # department are left out rather than shown as assignable.
        field_ids = get_field_employee_ids()
        report_ids = [rid for rid in report_ids if rid in field_ids]

        if not report_ids:
            return success_response(message="Team fetched successfully.", data=[])

        employees_resp = (
            supabase_admin.table("employees")
            .select(
                "id, employee_id, full_name, designation_id, designations(designation_name)"
            )
            .in_("id", report_ids)
            .execute()
        )

        assignments_resp = (
            supabase_admin.table("employee_site_assignments")
            .select(
                "employee_id, location_id, locations(id, location_name, location_code)"
            )
            .in_("employee_id", report_ids)
            .eq("is_active", True)
            .execute()
        )

        sites_by_employee: dict[str, list] = {}
        for row in assignments_resp.data or []:
            sites_by_employee.setdefault(row["employee_id"], []).append(
                row.get("locations")
            )

        team = []
        for emp in employees_resp.data or []:
            team.append(
                {
                    **emp,
                    "assigned_sites": sites_by_employee.get(emp["id"], []),
                }
            )

        return success_response(message="Team fetched successfully.", data=team)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch your team.")


# ==========================================================================
# READ — SITE ASSIGNMENT HISTORY FOR ONE EMPLOYEE
# ==========================================================================


def get_employee_site_assignments(employee_id: str, auth_user_id: str):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)
        caller_employee_id = manager_employee_id

        is_self = caller_employee_id == employee_id
        can_view = (
            is_self
            or has_permission(auth_user_id, "VIEW_SITE_ASSIGNMENTS")
            or has_permission(auth_user_id, "VIEW_ALL_ATTENDANCE")
        )

        if not can_view:
            forbidden(
                "You don't have permission to view this employee's site assignments."
            )

        if not is_self and not has_permission(auth_user_id, "VIEW_ALL_ATTENDANCE"):
            if not is_manager_of(caller_employee_id, employee_id):
                forbidden("You can only view site assignments for your own reports.")

        response = (
            supabase_admin.table("employee_site_assignments")
            .select(SITE_ASSIGNMENT_SELECT)
            .eq("employee_id", employee_id)
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Employee site assignments fetched successfully.",
            data=response.data or [],
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch employee site assignments.")


# ==========================================================================
# UPDATE / DEACTIVATE
# ==========================================================================


def update_site_assignment(
    assignment_id: str, data: UpdateSiteAssignmentRequest, auth_user_id: str
):
    try:
        existing = (
            supabase_admin.table("employee_site_assignments")
            .select("*")
            .eq("id", assignment_id)
            .maybe_single()
            .execute()
        )

        if not existing or not existing.data:
            not_found("Site assignment not found.")

        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not _can_manage_target(
            auth_user_id, manager_employee_id, existing.data["employee_id"]
        ):
            forbidden("You can only manage site assignments for your own team members.")

        update_data = data.model_dump(exclude_unset=True)

        if "assigned_from" in update_data and update_data["assigned_from"] is not None:
            update_data["assigned_from"] = update_data["assigned_from"].isoformat()
        if "assigned_to" in update_data and update_data["assigned_to"] is not None:
            update_data["assigned_to"] = update_data["assigned_to"].isoformat()

        response = (
            supabase_admin.table("employee_site_assignments")
            .update(update_data)
            .eq("id", assignment_id)
            .execute()
        )

        return success_response(
            message="Site assignment updated successfully.", data=response.data[0]
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update site assignment.")


def deactivate_site_assignment(assignment_id: str, auth_user_id: str):
    try:
        existing = (
            supabase_admin.table("employee_site_assignments")
            .select("*")
            .eq("id", assignment_id)
            .maybe_single()
            .execute()
        )

        if not existing or not existing.data:
            not_found("Site assignment not found.")

        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not _can_manage_target(
            auth_user_id, manager_employee_id, existing.data["employee_id"]
        ):
            forbidden("You can only manage site assignments for your own team members.")

        supabase_admin.table("employee_site_assignments").update(
            {"is_active": False}
        ).eq("id", assignment_id).execute()

        return success_response(
            message="Site assignment removed successfully.", data=None
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to remove site assignment.")
