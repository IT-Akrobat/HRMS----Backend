from fastapi import HTTPException, Request

from app.access_control.services import (
    get_access_control_settings,
    get_lockout_status,
    get_password_changed_at,
    is_ip_allowed,
    is_locked,
    is_password_expired,
    register_failed_attempt,
    reset_lockout,
    touch_password_changed_at,
)
from app.core.audit import record_audit_log
from app.core.database import supabase_admin
from app.core.exceptions import bad_request, forbidden, unauthorized
from app.core.database import supabase
from app.core.helpers.employee_helper import get_employee_by_code
from app.core.rbac import get_permissions_for_role
from app.core.sidebar import build_sidebar


def _client_ip(request: Request | None) -> str | None:
    if not request:
        return None
    # Behind a proxy/load balancer the real client IP is the first hop
    # in X-Forwarded-For; fall back to the direct connection otherwise.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def login_user(employee_code: str, password: str, request: Request = None):

    # Supabase Auth authenticates by email under the hood, so the
    # employee code typed into the login form is first resolved to the
    # email + id on file for that employee (see
    # app/core/helpers/employee_helper.get_employee_by_code). An unknown
    # code gets the exact same "Invalid credentials" error as a wrong
    # password, so login never reveals whether a given employee code
    # exists.
    employee = get_employee_by_code(employee_code)

    if not employee:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    email = employee["email"]
    employee_id = employee["id"]

    access_control = get_access_control_settings()

    # --- IP allowlist ---------------------------------------------------
    if access_control.get("restrict_to_office"):
        if not is_ip_allowed(
            _client_ip(request), access_control.get("allowed_ip_ranges") or []
        ):
            forbidden("This account can only sign in from the office network.")

    # --- Account lockout -------------------------------------------------
    lockout_row = get_lockout_status(employee_id)
    if is_locked(lockout_row):
        raise HTTPException(
            status_code=423,
            detail="Too many failed attempts. This account is temporarily locked -- try again later.",
        )

    try:

        response = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )

        if not response.session:

            register_failed_attempt(
                employee_id,
                access_control.get("lockout_attempts", 5),
                access_control.get("lockout_duration_minutes", 15),
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Successful sign-in clears any prior failed-attempt count.
        reset_lockout(employee_id)

        # Best-effort login audit trail (never blocks the response — see
        # app/core/audit.py). performed_by is the Supabase auth user id;
        # record_audit_log resolves it to an employees.id internally.
        record_audit_log(
            module="AUTH",
            action="LOGIN",
            performed_by=response.user.id if response.user else None,
            description=f"Login: {employee_code}",
            request=request,
        )

        # require_2fa / password expiry are surfaced as extra return
        # values rather than attributes stuck onto `response` -- it's a
        # Pydantic model from supabase-py and may reject attributes it
        # doesn't declare.
        #
        # mfa_required: no OTP challenge screen exists yet, so this is
        # informational only for now -- it doesn't block login.
        #
        # password_expired: real, based on user_profiles.password_changed_at
        # (see sql/018_password_expiry_tracking.sql). Login is still
        # allowed through (there's no pre-login reset flow to send an
        # expired-but-locked-out user to), but the frontend should treat
        # this as "force them to Settings > Security > Change password
        # before letting them do anything else."
        password_changed_at = get_password_changed_at(employee_id)
        password_expired = is_password_expired(
            password_changed_at, access_control.get("password_expiry_days")
        )

        return response, bool(access_control.get("require_2fa")), password_expired

    except HTTPException:
        raise

    except Exception:

        register_failed_attempt(
            employee_id,
            access_control.get("lockout_attempts", 5),
            access_control.get("lockout_duration_minutes", 15),
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")


# ==========================================
# POST /auth/refresh
# ==========================================
#
# Supabase access tokens are short-lived (~1hr). Until now the frontend
# stored the refresh_token from /auth/login but never used it, so every
# session died with "Invalid or expired token." once the access token
# expired, even though a valid refresh_token was sitting right there in
# sessionStorage. This exchanges that refresh_token for a fresh
# access_token (and rotates the refresh_token, since Supabase issues a
# new one on every refresh).
def refresh_user_session(refresh_token: str):

    try:

        response = supabase.auth.refresh_session(refresh_token)

        if not response.session:
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token."
            )

        return response

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")


# ==========================================
# POST /auth/change-password
# ==========================================
#
# Self-service password change for the logged-in user (any role — this
# isn't an admin resetting someone else's password, see
# app/employees/services.py for that flow if/when it exists).
#
# supabase-py has no standalone "verify this password without logging
# in" call, so the current password is checked by re-authenticating with
# it via supabase.auth.sign_in_with_password. That call failing means
# "current password is wrong", not "session expired" — this is a fresh
# check against Supabase, not a reuse of the caller's existing session
# token. Once verified, supabase_admin.auth.admin.update_user_by_id
# rotates the password using the service-role key (the anon client has
# no permission to change another session's password directly).
def change_password(
    auth_user, current_password: str, new_password: str, request: Request = None
):

    email = getattr(auth_user, "email", None)

    if not email:
        bad_request("This account has no email on file; password can't be verified.")

    if current_password == new_password:
        bad_request("New password must be different from your current password.")

    # Enforce Access Control > Password policy (min length + require
    # uppercase and number) rather than letting those toggles sit there
    # doing nothing.
    access_control = get_access_control_settings()

    min_length = access_control.get("password_min_length") or 8
    if len(new_password) < min_length:
        bad_request(f"Password must be at least {min_length} characters.")

    if access_control.get("password_require_complexity"):
        if not (
            any(c.isupper() for c in new_password)
            and any(c.isdigit() for c in new_password)
        ):
            bad_request(
                "Password must include at least one uppercase letter and one number."
            )

    try:

        verify = supabase.auth.sign_in_with_password(
            {"email": email, "password": current_password}
        )

        if not verify.session:
            bad_request("Current password is incorrect.")

    except HTTPException:
        raise

    except Exception:
        bad_request("Current password is incorrect.")

    try:

        supabase_admin.auth.admin.update_user_by_id(
            auth_user.id, {"password": new_password}
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(status_code=500, detail=f"Could not update password: {e}")

    # Resets the password-expiry clock (see
    # app/access_control/services.py::is_password_expired) and the audit
    # trail below -- neither should block the response if either fails.
    try:
        touch_password_changed_at(auth_user.id)
    except Exception:
        pass

    record_audit_log(
        module="AUTH",
        action="UPDATE",
        performed_by=auth_user.id,
        description="Password changed",
        request=request,
    )

    return {"message": "Password updated successfully."}


# ==========================================
# GET /auth/me
# ==========================================
#
# Single source of truth for "who is this user and what can they do",
# consumed by the frontend right after login to decide the redirect
# target and render the sidebar. See app/core/rbac.py (permissions) and
# app/core/sidebar.py (menu) for how each piece is actually computed —
# nothing here is a hardcoded per-role branch.

DEFAULT_REDIRECT_PATH = "/employee"


def get_me(auth_user) -> dict:
    profile_response = supabase_admin.table("user_profiles").select("""
        id,
        auth_user_id,
        is_active,
        role_id,

        roles(
            id,
            role_name,
            redirect_path
        ),

        employees(
            id,
            employee_id,
            full_name,
            email,
            phone,
            profile_photo,
            joining_date,
            employment_status,
            department_id,
            designation_id,
            date_of_birth,
            gender,
            marital_status,
            nationality,
            blood_group,
            religion,
            address,
            work_location,
            manager_id,

            departments!employees_department_id_fkey(
                id,
                department_name
            ),

            designations(
                id,
                designation_name
            ),

            shifts(
                id,
                shift_name,
                start_time,
                end_time
            )
        )
        """).eq("auth_user_id", auth_user.id).maybe_single().execute()

    if not profile_response or not profile_response.data:
        unauthorized("User profile not found.")

    profile = profile_response.data

    if profile.get("is_active") is False:
        forbidden("This account has been deactivated.")

    role = profile.get("roles")

    if not role:
        forbidden("Role not assigned.")

    role_id = role["id"]
    role_name = role["role_name"]

    employee = profile.get("employees") or {}
    department = employee.get("departments")
    designation = employee.get("designations")

    # Embedding this as a self-join (employees -> employees via manager_id)
    # depends on PostgREST having that FK in its schema-relationship cache,
    # which this environment doesn't reliably have (surfaced as a 500:
    # "Could not find a relationship between 'employees' and 'employees'").
    # A plain second lookup sidesteps that entirely — same data, no
    # dependency on the embed working. Mirrors how the Super Admin's
    # Employees page already resolves a manager: find-by-id rather than
    # embedding.
    manager = None
    manager_id = employee.get("manager_id")
    if manager_id:
        manager_response = (
            supabase_admin.table("employees")
            .select("id, employee_id, full_name")
            .eq("id", manager_id)
            .maybe_single()
            .execute()
        )
        manager = manager_response.data if manager_response else None

    permissions = get_permissions_for_role(role_id, role_name)
    sidebar = build_sidebar(role_name, role_id)
    allowed_modules = [item["key"] for item in sidebar]

    return {
        "id": auth_user.id,
        "name": employee.get("full_name") or (auth_user.email or "").split("@")[0],
        # HR/Super Admin edit the `employees` table's email (see
        # update_employee() in app/employees/services.py), not the
        # Supabase Auth login email. Returning auth_user.email here made
        # every profile/email display permanently stuck on whatever
        # email the account was created with -- edits from the Employee
        # Management screens never showed up here. employees.email is
        # the one HR actually manages, so it must be the source of
        # truth for what the employee sees.
        "email": employee.get("email") or auth_user.email,
        "role": role_name,
        "role_id": role_id,
        "organization": None,
        "branch": None,
        "department": department,
        "permissions": permissions,
        "allowed_modules": allowed_modules,
        "sidebar": sidebar,
        "redirect_path": role.get("redirect_path") or DEFAULT_REDIRECT_PATH,
        "theme": "light",
        "profile": {
            "id": employee.get("id"),
            "employee_id": employee.get("employee_id"),
            "full_name": employee.get("full_name"),
            "phone": employee.get("phone"),
            "profile_photo": employee.get("profile_photo"),
            "joining_date": (
                str(employee.get("joining_date"))
                if employee.get("joining_date")
                else None
            ),
            "employment_status": employee.get("employment_status"),
            "designation": designation,
            # Previously missing here even though the employees table row
            # already had them — this is what left the employee's own
            # Job Details tab showing "—" for Work Location, Reporting
            # Manager, and Shift while the Super Admin's employee detail
            # panel (which queries the employees table directly with the
            # same joins) showed the real values for the same person.
            "work_location": employee.get("work_location"),
            "manager": manager,
            "shift": employee.get("shifts"),
            "date_of_birth": (
                str(employee.get("date_of_birth"))
                if employee.get("date_of_birth")
                else None
            ),
            "gender": employee.get("gender"),
            "marital_status": employee.get("marital_status"),
            "nationality": employee.get("nationality"),
            "blood_group": employee.get("blood_group"),
            "religion": employee.get("religion"),
            "address": employee.get("address"),
        },
    }
