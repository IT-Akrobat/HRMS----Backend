# from typing import Optional

# from fastapi import HTTPException, Request

# from app.core.database import supabase_admin
# from app.core.repository import SupabaseRepository
# from app.core.responses import success_response
# from app.core.logger import logger
# from app.core.exceptions import internal_server_error, conflict
# from app.core.messages import EMPLOYEE_CREATED, EMPLOYEE_UPDATED, EMPLOYEE_DELETED
# from app.core.helpers.employee_helper import (
#     generate_employee_id,
#     validate_company_email,
#     check_email_exists,
#     validate_reference,
#     get_employee_or_404,
# )
# from app.core.audit import record_audit_log

# employee_repo = SupabaseRepository("employees")

# EMPLOYEE_LIST_SELECT = """
#     *,
#     departments(id, department_name),
#     designations(id, designation_name),
#     shifts(id, shift_name)
# """


# # ==========================================
# # GET EMPLOYEES
# # ==========================================


# def get_employees(
#     department_id: Optional[str] = None,
#     designation_id: Optional[str] = None,
#     role_id: Optional[str] = None,
# ):
#     try:
#         employees, _total = employee_repo.list(
#             select=EMPLOYEE_LIST_SELECT,
#             filters={
#                 "department_id": department_id,
#                 "designation_id": designation_id,
#             },
#         )

#         if role_id:
#             profiles = (
#                 supabase_admin.table("user_profiles")
#                 .select("employee_id")
#                 .eq("role_id", role_id)
#                 .execute()
#             )

#             employee_ids = {row["employee_id"] for row in profiles.data}

#             employees = [emp for emp in employees if emp["id"] in employee_ids]

#         return success_response(
#             message="Employees fetched successfully.",
#             data=employees,
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch employees.")


# # ==========================================
# # CREATE EMPLOYEE
# # ==========================================


# def create_employee(data, current_user=None, request: Optional[Request] = None):

#     auth_user_id = None

#     try:
#         validate_company_email(data.email)
#         check_email_exists(data.email)

#         validate_reference("departments", data.department_id, "Department")
#         validate_reference("designations", data.designation_id, "Designation")
#         validate_reference("shifts", data.shift_id, "Shift")
#         validate_reference("roles", data.role_id, "Role")
#         validate_reference("employees", data.manager_id, "Manager")

#         auth_user = supabase_admin.auth.admin.create_user(
#             {
#                 "email": data.email,
#                 "password": data.password,
#                 "email_confirm": True,
#             }
#         )

#         auth_user_id = auth_user.user.id

#         employee_data = employee_repo.create(
#             {
#                 "employee_id": generate_employee_id(),
#                 "full_name": data.full_name,
#                 "email": data.email,
#                 "phone": data.phone,
#                 "department_id": (
#                     str(data.department_id) if data.department_id else None
#                 ),
#                 "designation_id": (
#                     str(data.designation_id) if data.designation_id else None
#                 ),
#                 "manager_id": str(data.manager_id) if data.manager_id else None,
#                 "joining_date": str(data.joining_date) if data.joining_date else None,
#                 "employment_status": data.employment_status,
#                 "work_location": data.work_location,
#                 "shift_id": str(data.shift_id) if data.shift_id else None,
#                 "profile_photo": data.profile_photo,
#             }
#         )

#         supabase_admin.table("user_profiles").insert(
#             {
#                 "auth_user_id": auth_user_id,
#                 "employee_id": employee_data["id"],
#                 "role_id": str(data.role_id),
#             }
#         ).execute()

#         record_audit_log(
#             module="EMPLOYEE",
#             action="CREATE",
#             performed_by=getattr(current_user, "id", None),
#             target_employee_id=employee_data["id"],
#             record_id=employee_data["id"],
#             description=f"{employee_data['full_name']} created",
#             new_values=employee_data,
#             request=request,
#         )

#         return success_response(
#             message=EMPLOYEE_CREATED,
#             data=employee_data,
#         )

#     except HTTPException:
#         # Roll back the auth user so we don't leak logins for employees
#         # that failed to persist.
#         if auth_user_id:
#             try:
#                 supabase_admin.auth.admin.delete_user(auth_user_id)
#             except Exception as rollback_error:
#                 logger.exception(rollback_error)
#         raise

#     except Exception as e:
#         logger.exception(e)

#         if auth_user_id:
#             try:
#                 supabase_admin.auth.admin.delete_user(auth_user_id)
#             except Exception as rollback_error:
#                 logger.exception(rollback_error)

#         internal_server_error("Unable to create employee.")


# # ==========================================
# # UPDATE EMPLOYEE
# # ==========================================


# def update_employee(
#     employee_id: str,
#     data,
#     current_user=None,
#     request: Optional[Request] = None,
# ):
#     try:
#         existing_employee = get_employee_or_404(employee_id)

#         update_data = data.model_dump(exclude_unset=True)

#         if "email" in update_data and update_data["email"]:
#             validate_company_email(update_data["email"])

#             if (
#                 employee_repo.find_one({"email": update_data["email"]}) not in (None,)
#                 and employee_repo.find_one({"email": update_data["email"]}).get("id")
#                 != employee_id
#             ):
#                 conflict("Email already exists.")

#         if "department_id" in update_data:
#             validate_reference(
#                 "departments", update_data["department_id"], "Department"
#             )

#         if "role_id" in update_data:
#             validate_reference("roles", update_data["role_id"], "Role")

#             supabase_admin.table("user_profiles").update(
#                 {"role_id": str(update_data["role_id"])}
#             ).eq("employee_id", employee_id).execute()

#             update_data.pop("role_id")

#         if "designation_id" in update_data:
#             validate_reference(
#                 "designations", update_data["designation_id"], "Designation"
#             )

#         if "shift_id" in update_data:
#             validate_reference("shifts", update_data["shift_id"], "Shift")

#         if "manager_id" in update_data:
#             validate_reference("employees", update_data["manager_id"], "Manager")

#         # UUID fields must be stringified for the Supabase client.
#         for key in ("department_id", "designation_id", "shift_id", "manager_id"):
#             if key in update_data and update_data[key] is not None:
#                 update_data[key] = str(update_data[key])

#         for key in ("joining_date",):
#             if key in update_data and update_data[key] is not None:
#                 update_data[key] = str(update_data[key])

#         updated_employee = employee_repo.update(employee_id, update_data)

#         record_audit_log(
#             module="EMPLOYEE",
#             action="UPDATE",
#             performed_by=getattr(current_user, "id", None),
#             target_employee_id=employee_id,
#             record_id=employee_id,
#             description=f"{updated_employee['full_name']} updated",
#             old_values=existing_employee,
#             new_values=updated_employee,
#             request=request,
#         )

#         return success_response(
#             message=EMPLOYEE_UPDATED,
#             data=updated_employee,
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to update employee.")


# # ==========================================
# # DELETE EMPLOYEE
# # ==========================================


# def delete_employee(
#     employee_id: str,
#     current_user=None,
#     request: Optional[Request] = None,
# ):
#     try:
#         employee = get_employee_or_404(employee_id)

#         profile = (
#             supabase_admin.table("user_profiles")
#             .select("id,auth_user_id")
#             .eq("employee_id", employee_id)
#             .maybe_single()
#             .execute()
#         )

#         if profile and profile.data:
#             try:
#                 supabase_admin.auth.admin.delete_user(profile.data["auth_user_id"])
#             except Exception:
#                 logger.warning("Unable to delete auth user.")

#             supabase_admin.table("user_profiles").delete().eq(
#                 "employee_id", employee_id
#             ).execute()

#         employee_repo.delete(employee_id)

#         record_audit_log(
#             module="EMPLOYEE",
#             action="DELETE",
#             performed_by=getattr(current_user, "id", None),
#             target_employee_id=employee_id,
#             record_id=employee_id,
#             description=f"{employee['full_name']} deleted",
#             old_values=employee,
#             request=request,
#         )

#         return success_response(message=EMPLOYEE_DELETED)

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to delete employee.")
from typing import Optional

from fastapi import HTTPException, Request

from app.core.database import supabase_admin
from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import internal_server_error, conflict, bad_request
from app.core.messages import EMPLOYEE_CREATED, EMPLOYEE_UPDATED, EMPLOYEE_DELETED
from app.core.constants import ADMIN
from app.core.helpers.employee_helper import (
    generate_employee_id,
    generate_temp_password,
    check_email_exists,
    validate_reference,
    get_employee_or_404,
    resolve_default_shift_id,
    get_employee_id_for_auth_user,
    get_all_report_ids,
    is_field_employee,
)
from app.core.validators import validate_email
from app.core.audit import record_audit_log
from app.leaves.policy_services import (
    assign_employee_leave_tier,
    evaluate_leave_eligibility,
    get_leave_type_or_404,
    CHILDCARE_LEAVE,
    ANNUAL_LEAVE,
)

employee_repo = SupabaseRepository("employees")

EMPLOYEE_LIST_SELECT = """
    *,
    departments!employees_department_id_fkey(id, department_name),
    designations(id, designation_name),
    shifts(id, shift_name)
"""


# ==========================================
# GET EMPLOYEES
# ==========================================


def get_employees(
    department_id: Optional[str] = None,
    designation_id: Optional[str] = None,
    role_id: Optional[str] = None,
):
    try:
        employees, _total = employee_repo.list(
            select=EMPLOYEE_LIST_SELECT,
            filters={
                "department_id": department_id,
                "designation_id": designation_id,
            },
        )

        if role_id:
            profiles = (
                supabase_admin.table("user_profiles")
                .select("employee_id")
                .eq("role_id", role_id)
                .execute()
            )

            employee_ids = {row["employee_id"] for row in profiles.data}

            employees = [emp for emp in employees if emp["id"] in employee_ids]

        return success_response(
            message="Employees fetched successfully.",
            data=employees,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch employees.")


# ==========================================
# PREVIEW EMPLOYEE CODE
# ==========================================
#
# Lets the Add User form show the AKR-DEPT-DESIG-#### code live as HR
# picks a department/designation, before the employee is actually
# created. Just calls the same generator create_employee() uses --
# read-only, no rows are written, so it's safe to call on every
# department/designation change.


def preview_employee_code(
    department_id: Optional[str] = None,
    designation_id: Optional[str] = None,
):
    try:
        code = generate_employee_id(department_id, designation_id)
        return success_response(
            message="Employee code generated.",
            data={"employee_id": code},
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to generate employee code.")


# ==========================================
# CREATE EMPLOYEE
# ==========================================


def create_employee(data, current_user=None, request: Optional[Request] = None):

    auth_user_id = None

    try:
        # Email is required -- no more optional-email flow, and no more
        # placeholder login derived from the employee code. Format is
        # checked (any domain is fine, not just @akrobat.com.sg), and
        # uniqueness is checked before we touch Supabase auth.
        validate_email(data.email)
        check_email_exists(data.email)

        validate_reference("departments", data.department_id, "Department")
        validate_reference("designations", data.designation_id, "Designation")
        validate_reference("shifts", data.shift_id, "Shift")
        validate_reference("roles", data.role_id, "Role")
        validate_reference("employees", data.manager_id, "Manager")

        # SUPER ADMIN can never be handed out through this endpoint, even
        # to a caller who is themselves SUPER ADMIN or HR (both of whom
        # otherwise pass the require_role gate above and can set role_id
        # to anything that exists in `roles`). The one fixed Super Admin
        # login (IT@akrobat.com.sg) is bootstrapped exclusively via
        # scripts/create_super_admin.py, run from the backend terminal --
        # never through the API/UI. This is the actual guard; the
        # frontend also hides SUPER ADMIN from the role dropdown, but
        # that's just UX and isn't sufficient on its own since role_id is
        # a plain field on the request body.
        role_row = (
            supabase_admin.table("roles")
            .select("role_name")
            .eq("id", str(data.role_id))
            .maybe_single()
            .execute()
        )
        if (
            role_row
            and role_row.data
            and (role_row.data.get("role_name") or "").strip().upper() == ADMIN
        ):
            bad_request(
                "SUPER ADMIN cannot be assigned here. It is created only "
                "via scripts/create_super_admin.py from the server terminal."
            )

        # Working hours must be set at creation time. If HR didn't pick a
        # shift explicitly, fall back to the designation's default_shift_id
        # (Office / Operation Site / Inspection Site / Work Shop hours,
        # seeded from the Attendance Info doc — see
        # sql/014_designation_shifts_and_site_visits.sql). This is what
        # drives every later late/overtime/working-hours calculation in
        # app/attendance/services.py, so a shift must be resolved here,
        # not left for the employee's first check-in to discover it's null.
        resolved_shift_id = str(data.shift_id) if data.shift_id else None
        if not resolved_shift_id and data.designation_id:
            resolved_shift_id = resolve_default_shift_id(str(data.designation_id))

        # Employee code is derived from the chosen department + designation
        # (AKR-HR-EXE-0001, AKR-FIN-0002, ...) and the login password is
        # generated server-side -- neither is taken from the request
        # anymore (see app/employees/schemas.py EmployeeCreate and
        # app/core/helpers/employee_helper.py).
        new_employee_id = generate_employee_id(
            str(data.department_id) if data.department_id else None,
            str(data.designation_id) if data.designation_id else None,
        )
        generated_password = generate_temp_password()

        employee_email = data.email

        auth_user = supabase_admin.auth.admin.create_user(
            {
                "email": employee_email,
                "password": generated_password,
                "email_confirm": True,
            }
        )

        auth_user_id = auth_user.user.id

        employee_data = employee_repo.create(
            {
                "employee_id": new_employee_id,
                "full_name": data.full_name,
                "email": employee_email,
                "phone": data.phone,
                "department_id": (
                    str(data.department_id) if data.department_id else None
                ),
                "designation_id": (
                    str(data.designation_id) if data.designation_id else None
                ),
                "manager_id": str(data.manager_id) if data.manager_id else None,
                "joining_date": str(data.joining_date) if data.joining_date else None,
                "date_of_birth": (
                    str(data.date_of_birth) if data.date_of_birth else None
                ),
                "employment_status": data.employment_status,
                "work_location": data.work_location,
                "shift_id": resolved_shift_id,
                "profile_photo": data.profile_photo,
                "gender": data.gender,
                "marital_status": data.marital_status,
                "nationality": data.nationality,
                "working_days_per_week": data.working_days_per_week,
            }
        )

        # Annual Leave tier is required for every employee (21/20/14/
        # 11/10 days). Childcare Leave tier is only assigned if the
        # employee is actually eligible (married) -- assign_employee_
        # leave_tier() itself doesn't check eligibility (HR may be
        # pre-configuring ahead of a marital-status update), so gate it
        # here based on the fields just saved above.
        assign_employee_leave_tier(
            employee_data["id"],
            ANNUAL_LEAVE,
            str(data.annual_leave_tier_id),
            assigned_by=getattr(current_user, "id", None),
        )

        if data.childcare_leave_tier_id:
            childcare_type = get_leave_type_or_404(CHILDCARE_LEAVE)
            eligible, _reason = evaluate_leave_eligibility(
                employee_data, childcare_type["id"]
            )
            if eligible:
                assign_employee_leave_tier(
                    employee_data["id"],
                    CHILDCARE_LEAVE,
                    str(data.childcare_leave_tier_id),
                    assigned_by=getattr(current_user, "id", None),
                )

        supabase_admin.table("user_profiles").insert(
            {
                "auth_user_id": auth_user_id,
                "employee_id": employee_data["id"],
                "role_id": str(data.role_id),
            }
        ).execute()

        record_audit_log(
            module="EMPLOYEE",
            action="CREATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=employee_data["id"],
            record_id=employee_data["id"],
            description=f"{employee_data['full_name']} created",
            new_values=employee_data,
            request=request,
        )

        # login_employee_id/login_password are only ever present in this
        # one create response -- they are not stored anywhere in
        # plaintext and are not returned by GET/PUT endpoints. Password
        # is set via Supabase's admin API on create, so the employee
        # (or HR, on their behalf) should change it after first login.
        return success_response(
            message=EMPLOYEE_CREATED,
            data={
                **employee_data,
                "login_employee_id": new_employee_id,
                "login_password": generated_password,
            },
        )

    except HTTPException:
        # Roll back the auth user so we don't leak logins for employees
        # that failed to persist.
        if auth_user_id:
            try:
                supabase_admin.auth.admin.delete_user(auth_user_id)
            except Exception as rollback_error:
                logger.exception(rollback_error)
        raise

    except Exception as e:
        logger.exception(e)

        if auth_user_id:
            try:
                supabase_admin.auth.admin.delete_user(auth_user_id)
            except Exception as rollback_error:
                logger.exception(rollback_error)

        internal_server_error("Unable to create employee.")


# ==========================================
# UPDATE EMPLOYEE
# ==========================================


def update_employee(
    employee_id: str,
    data,
    current_user=None,
    request: Optional[Request] = None,
):
    try:
        existing_employee = get_employee_or_404(employee_id)

        update_data = data.model_dump(exclude_unset=True)

        if "email" in update_data and update_data["email"]:
            validate_email(update_data["email"])

            if (
                employee_repo.find_one({"email": update_data["email"]}) not in (None,)
                and employee_repo.find_one({"email": update_data["email"]}).get("id")
                != employee_id
            ):
                conflict("Email already exists.")

        if "department_id" in update_data:
            validate_reference(
                "departments", update_data["department_id"], "Department"
            )

        if "role_id" in update_data:
            validate_reference("roles", update_data["role_id"], "Role")

            supabase_admin.table("user_profiles").update(
                {"role_id": str(update_data["role_id"])}
            ).eq("employee_id", employee_id).execute()

            update_data.pop("role_id")

        if "designation_id" in update_data:
            validate_reference(
                "designations", update_data["designation_id"], "Designation"
            )

        # Leave tier assignments aren't columns on `employees` itself --
        # pulled out here and applied to employee_leave_tier separately,
        # after the main employee row is updated below.
        annual_leave_tier_id = update_data.pop("annual_leave_tier_id", None)
        childcare_leave_tier_id = update_data.pop("childcare_leave_tier_id", None)

        if "shift_id" in update_data:
            validate_reference("shifts", update_data["shift_id"], "Shift")

        if "manager_id" in update_data:
            validate_reference("employees", update_data["manager_id"], "Manager")

        # UUID fields must be stringified for the Supabase client.
        for key in ("department_id", "designation_id", "shift_id", "manager_id"):
            if key in update_data and update_data[key] is not None:
                update_data[key] = str(update_data[key])

        for key in ("joining_date", "date_of_birth"):
            if key in update_data and update_data[key] is not None:
                update_data[key] = str(update_data[key])

        updated_employee = employee_repo.update(employee_id, update_data)

        # Leave tier reassignment. assign_employee_leave_tier() upserts
        # (one row per employee+leave_type via the unique constraint), so
        # this is safe to call whenever HR changes an employee's tier,
        # not just at creation. Childcare Leave tier is only actually
        # applied if the employee (post-update) passes eligibility --
        # HR may set marital_status and the childcare tier in the same
        # edit, so eligibility is checked against `updated_employee`,
        # not the stale `existing_employee`.
        if annual_leave_tier_id:
            assign_employee_leave_tier(
                employee_id,
                ANNUAL_LEAVE,
                str(annual_leave_tier_id),
                assigned_by=getattr(current_user, "id", None),
            )

        if childcare_leave_tier_id:
            childcare_type = get_leave_type_or_404(CHILDCARE_LEAVE)
            eligible, _reason = evaluate_leave_eligibility(
                updated_employee, childcare_type["id"]
            )
            if eligible:
                assign_employee_leave_tier(
                    employee_id,
                    CHILDCARE_LEAVE,
                    str(childcare_leave_tier_id),
                    assigned_by=getattr(current_user, "id", None),
                )
            else:
                logger.info(
                    f"Skipped Childcare Leave tier assignment for "
                    f"{employee_id}: not eligible."
                )

        # The employees.email column HR/Super Admin just edited above is
        # a completely separate value from the Supabase Auth login email
        # the employee actually authenticates with -- create_employee()
        # only ever sets the auth email once, at creation. Without this,
        # editing an employee's email here silently does nothing to
        # their login: get_me() previously even read auth_user.email
        # directly (now fixed to prefer employees.email — see
        # app/auth/services.py), but the employee still couldn't log in
        # with the new address, and any password-reset email would keep
        # going to the old one. Keep both in sync whenever email changes.
        if "email" in update_data and update_data["email"]:
            try:
                profile_lookup = (
                    supabase_admin.table("user_profiles")
                    .select("auth_user_id")
                    .eq("employee_id", employee_id)
                    .maybe_single()
                    .execute()
                )
                auth_user_id = (
                    profile_lookup.data.get("auth_user_id")
                    if profile_lookup and profile_lookup.data
                    else None
                )
                if auth_user_id:
                    supabase_admin.auth.admin.update_user_by_id(
                        auth_user_id,
                        {"email": update_data["email"], "email_confirm": True},
                    )
            except Exception as e:
                # Don't fail the whole employee update over this -- the
                # employees.email column (what HR/get_me() see) is
                # already saved; log it so the auth-email mismatch can
                # be caught and fixed rather than silently lost.
                logger.error(
                    f"Failed to sync Supabase Auth login email for "
                    f"employee {employee_id} after email change: {e}"
                )

        # If this update touched the department, re-check field-employee
        # status against the NEW department. Site assignment (and the
        # site check-in banner it drives) is only ever meant to apply to
        # Inspection/Operation field staff — see
        # app/site_assignments/services.py::_require_field_employee, which
        # blocks *creating* a new assignment for anyone else. But moving
        # an employee OUT of Inspection/Operation doesn't retroactively
        # touch any assignment they already had, so without this they'd
        # keep seeing "Your manager assigned you to <site>" on the office
        # check-in screen even after becoming office staff. Deactivating
        # here (not deleting, so the history/audit trail is preserved)
        # keeps the office check-in flow from ever mixing with stale site
        # data.
        if "department_id" in update_data and not is_field_employee(employee_id):
            try:
                supabase_admin.table("employee_site_assignments").update(
                    {"is_active": False}
                ).eq("employee_id", employee_id).eq("is_active", True).execute()
            except Exception as e:
                logger.error(
                    f"Failed to clear stale site assignment(s) for "
                    f"{employee_id} after department change: {e}"
                )

        record_audit_log(
            module="EMPLOYEE",
            action="UPDATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=employee_id,
            record_id=employee_id,
            description=f"{updated_employee['full_name']} updated",
            old_values=existing_employee,
            new_values=updated_employee,
            request=request,
        )

        return success_response(
            message=EMPLOYEE_UPDATED,
            data=updated_employee,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update employee.")


# ==========================================
# UPDATE MY OWN PERSONAL DETAILS ("My Profile")
# ==========================================
# Self-service counterpart to update_employee(): any signed-in user can
# call this for their OWN record (no EDIT_EMPLOYEE permission needed),
# but only with the narrow EmployeeSelfUpdate fields (phone + personal
# details) -- never job/role fields. Backs the My Profile page's
# "Edit Profile" popup, replacing what used to be saved to
# localStorage only (date_of_birth, gender, marital_status,
# nationality, blood_group, religion, address).


def update_my_profile(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            conflict("No employee record is linked to this account.")

        existing_employee = get_employee_or_404(employee_id)

        update_data = data.model_dump(exclude_unset=True)

        if "date_of_birth" in update_data and update_data["date_of_birth"] is not None:
            update_data["date_of_birth"] = str(update_data["date_of_birth"])

        if not update_data:
            return success_response(
                message="Nothing to update.", data=existing_employee
            )

        updated_employee = employee_repo.update(employee_id, update_data)

        record_audit_log(
            module="EMPLOYEE",
            action="UPDATE",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=employee_id,
            description=f"{updated_employee['full_name']} updated their own profile",
            old_values=existing_employee,
            new_values=updated_employee,
            request=request,
        )

        return success_response(
            message="Profile updated successfully.",
            data=updated_employee,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update your profile.")


# ==========================================
# DELETE EMPLOYEE
# ==========================================


def delete_employee(
    employee_id: str,
    current_user=None,
    request: Optional[Request] = None,
):
    try:
        employee = get_employee_or_404(employee_id)

        profile = (
            supabase_admin.table("user_profiles")
            .select("id,auth_user_id")
            .eq("employee_id", employee_id)
            .maybe_single()
            .execute()
        )

        if profile and profile.data:
            try:
                supabase_admin.auth.admin.delete_user(profile.data["auth_user_id"])
            except Exception:
                logger.warning("Unable to delete auth user.")

            supabase_admin.table("user_profiles").delete().eq(
                "employee_id", employee_id
            ).execute()

        employee_repo.delete(employee_id)

        record_audit_log(
            module="EMPLOYEE",
            action="DELETE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=employee_id,
            record_id=employee_id,
            description=f"{employee['full_name']} deleted",
            old_values=employee,
            request=request,
        )

        return success_response(message=EMPLOYEE_DELETED)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to delete employee.")


# ==========================================
# GET MY TEAM (Manager — direct + indirect reports only)
# ==========================================
#
# Same "manager scope" pattern as get_team_leaves() in app/leaves/services.py
# and get_team_attendance() in app/attendance/services.py: resolve the
# caller's own employee_id, walk the org chart down via get_all_report_ids(),
# then fetch full employee records (with department/designation/shift
# embeds, same shape as GET /employees/) for exactly that set — nothing
# outside the caller's own reporting line is ever returned.


def get_my_team_employees(auth_user_id: str):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(message="Team fetched successfully.", data=[])

        report_ids = get_all_report_ids(manager_employee_id)

        if not report_ids:
            return success_response(message="Team fetched successfully.", data=[])

        response = (
            supabase_admin.table("employees")
            .select(EMPLOYEE_LIST_SELECT)
            .in_("id", report_ids)
            .order("full_name")
            .execute()
        )

        return success_response(
            message="Team fetched successfully.", data=response.data or []
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch team.")
