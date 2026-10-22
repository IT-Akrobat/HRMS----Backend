import hmac
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from app.access_control.services import (
    clear_session_invalidation,
    get_access_control_settings,
    get_lockout_status,
    get_password_changed_at,
    invalidate_sessions,
    is_ip_allowed,
    is_locked,
    is_password_expired,
    is_session_invalidated,
    register_failed_attempt,
    reset_lockout,
    touch_password_changed_at,
)
from app.core.audit import record_audit_log
from app.core.database import supabase_admin
from app.core.logger import logger
from app.core.exceptions import bad_request, forbidden, unauthorized
from app.core.database import supabase
from app.core.helpers.employee_helper import (
    find_employees_by_username,
    generate_temp_password,
    is_placeholder_email,
    placeholder_login_email,
)
from app.core.rbac import get_permissions_for_role
from app.core.request_ip import get_client_ip
from app.core.sidebar import build_sidebar


def _client_ip(request: Request | None) -> str | None:
    # Kept as a thin wrapper (rather than a straight import everywhere)
    # so existing call sites in this file don't all need touching --
    # see app/core/request_ip.py for the actual logic and why it exists.
    return get_client_ip(request)


# ==========================================
# FORCED PASSWORD CHANGE MARKER
# ==========================================
#
# After a "forgot password" reset the user is holding a temporary password
# that was shown on screen, so it must be replaced on first login. Rather
# than add a column, user_profiles.password_changed_at is set to the Unix
# epoch as a marker. login_user() reports password_expired=True for it (the
# frontend then sends the user to Settings > Security), and
# change_password() -> touch_password_changed_at() overwrites it with the
# real time, which clears the flag.

_FORCE_CHANGE_MARKER = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _is_force_change_marker(password_changed_at) -> bool:
    return bool(password_changed_at) and password_changed_at <= datetime(
        2000, 1, 1, tzinfo=timezone.utc
    )


def _mark_password_must_change(auth_user_id: str):
    supabase_admin.table("user_profiles").update(
        {"password_changed_at": _FORCE_CHANGE_MARKER.isoformat()}
    ).eq("auth_user_id", auth_user_id).execute()


def login_user(username: str, password: str, request: Request = None):

    # Supabase Auth authenticates by email under the hood, so the
    # username typed into the login form (the employee's full name) is
    # first resolved to the email + id on file for that employee (see
    # app/core/helpers/employee_helper.find_employees_by_username). An
    # unknown username gets the exact same "Invalid credentials" error as
    # a wrong password, so login never reveals whether a name exists.
    matches = find_employees_by_username(username)

    if not matches:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Names are kept unique when employees are created/edited, so this
    # only happens for old records that already shared a name.
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail="More than one account uses this username. Please contact HR.",
        )

    employee = matches[0]

    # Employees created without an email have employees.email = NULL;
    # their Supabase Auth login uses an internal placeholder derived from
    # the employee code (see employee_helper.placeholder_login_email).
    email = employee.get("email") or placeholder_login_email(employee["employee_id"])
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

    # --- Credential check -- the ONLY thing that should ever produce
    # "Invalid credentials" or increment the failed-attempt counter.
    # Anything below this point runs only after a real, successful sign-
    # in and must never be able to turn a correct password into a
    # rejected login. --------------------------------------------------
    try:
        response = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except Exception:
        response = None

    if not response or not response.session:
        register_failed_attempt(
            employee_id,
            access_control.get("lockout_attempts", 5),
            access_control.get("lockout_duration_minutes", 15),
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # --- Post-login side effects -- each is independently best-effort.
    # A bug or missing table in any one of these must not undo a login
    # that Supabase already confirmed was valid. ------------------------
    try:
        # Clears any prior failed-attempt count and any prior "Force
        # logout all" block -- a real login with real credentials is
        # exactly the thing that should lift both.
        reset_lockout(employee_id)
        if response.user:
            clear_session_invalidation(response.user.id)
    except Exception as e:
        print("LOGIN POST-PROCESSING WARNING (lockout/invalidation):", e)

    # Best-effort login audit trail (never blocks the response — see
    # app/core/audit.py). performed_by is the Supabase auth user id;
    # record_audit_log resolves it to an employees.id internally.
    record_audit_log(
        module="AUTH",
        action="LOGIN",
        performed_by=response.user.id if response.user else None,
        description=f"Login: {employee['full_name']}",
        request=request,
    )

    # require_2fa / password expiry are surfaced as extra return values
    # rather than attributes stuck onto `response` -- it's a Pydantic
    # model from supabase-py and may reject attributes it doesn't
    # declare.
    #
    # mfa_required: no OTP challenge screen exists yet, so this is
    # informational only for now -- it doesn't block login.
    #
    # password_expired: real, based on user_profiles.password_changed_at
    # (see sql/018_password_expiry_tracking.sql). Login is still allowed
    # through (there's no pre-login reset flow to send an
    # expired-but-locked-out user to), but the frontend should treat
    # this as "force them to Settings > Security > Change password
    # before letting them do anything else."
    try:
        password_changed_at = get_password_changed_at(employee_id)
        password_expired = is_password_expired(
            password_changed_at, access_control.get("password_expiry_days")
        ) or _is_force_change_marker(password_changed_at)
    except Exception as e:
        print("LOGIN POST-PROCESSING WARNING (password expiry):", e)
        password_expired = False

    return response, bool(access_control.get("require_2fa")), password_expired


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

        # Without this, a force-logged-out user's still-valid
        # refresh_token would happily mint a brand new access token here
        # and silently undo the force logout (see
        # app/access_control/services.py::is_session_invalidated).
        if response.user and is_session_invalidated(response.user.id):
            raise HTTPException(
                status_code=401,
                detail="Your session was ended by an administrator. Please log in again.",
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
# POST /auth/forgot-password
# ==========================================
#
# Self-service reset for employees who have no real email on file (so no
# reset link can be mailed). The caller proves who they are with their
# username + employee code; if both match, a new temporary password is
# generated, set on the Supabase Auth user, and returned ONCE in the
# response. The user logs in with it and is forced to pick their own
# password (see _FORCE_CHANGE_MARKER above).
#
# Abuse limits: 3 requests/minute per IP (route), and a wrong employee
# code for an existing username counts toward the same per-account
# lockout as wrong login passwords -- so the code can't be brute-forced.
# A locked account can't be reset until the lock expires.

_RESET_MISMATCH = "Username and employee code do not match."


def _norm_code(value: str | None) -> str:
    return "".join((value or "").split()).casefold()


def reset_password_with_employee_code(
    username: str, employee_code: str, request: Request = None
):
    matches = find_employees_by_username(username)

    # Unknown / ambiguous username gets the same message as a wrong code.
    if len(matches) != 1:
        raise HTTPException(status_code=400, detail=_RESET_MISMATCH)

    employee = matches[0]
    employee_pk = employee["id"]

    access_control = get_access_control_settings()

    if is_locked(get_lockout_status(employee_pk)):
        raise HTTPException(
            status_code=423,
            detail="Too many failed attempts. This account is temporarily locked -- try again later.",
        )

    expected = _norm_code(employee.get("employee_id"))
    given = _norm_code(employee_code)

    if not expected or not hmac.compare_digest(expected.encode(), given.encode()):
        register_failed_attempt(
            employee_pk,
            access_control.get("lockout_attempts", 5),
            access_control.get("lockout_duration_minutes", 15),
        )
        raise HTTPException(status_code=400, detail=_RESET_MISMATCH)

    profile = (
        supabase_admin.table("user_profiles")
        .select("auth_user_id, is_active")
        .eq("employee_id", employee_pk)
        .maybe_single()
        .execute()
    )

    if not profile or not profile.data or not profile.data.get("auth_user_id"):
        raise HTTPException(
            status_code=400,
            detail="This account can't be reset online. Please contact HR.",
        )

    if profile.data.get("is_active") is False:
        raise HTTPException(
            status_code=403,
            detail="This account is inactive. Please contact HR.",
        )

    auth_user_id = profile.data["auth_user_id"]
    temp_password = generate_temp_password()

    try:
        supabase_admin.auth.admin.update_user_by_id(
            auth_user_id, {"password": temp_password}
        )
    except Exception as e:
        logger.warning(f"Forgot-password update failed: {e}")
        raise HTTPException(status_code=500, detail="Could not reset password.")

    # Best-effort follow-ups -- none may undo a reset that already worked.
    try:
        _mark_password_must_change(auth_user_id)
    except Exception as e:
        print("FORGOT PASSWORD WARNING (must-change marker):", e)

    try:
        reset_lockout(employee_pk)
    except Exception as e:
        print("FORGOT PASSWORD WARNING (lockout reset):", e)

    try:
        # End sessions opened with the old password. The user's next real
        # login (with the temp password) lifts this block automatically.
        invalidate_sessions([auth_user_id])
    except Exception as e:
        print("FORGOT PASSWORD WARNING (invalidate sessions):", e)

    record_audit_log(
        module="AUTH",
        action="UPDATE",
        performed_by=auth_user_id,
        description=f"Password reset via forgot-password: {employee['full_name']}",
        request=request,
    )

    return {
        "message": "Your password has been reset. Sign in with the temporary password below, then set your own.",
        "temp_password": temp_password,
    }


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
            working_location,
            manager_id,
            outdoor_checkin_enabled,

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

    # True when somebody reports to this person -- i.e. they approve leave
    # for them. Drives the "Team Leave Requests" menu item for ANY role.
    is_reporting_manager = False
    if employee.get("id"):
        # Two separate lookups (instead of one .or_()) so a failure in one
        # -- e.g. employees.leave_manager_id missing because sql/033.sql
        # hasn't been run on this database -- can't hide a valid result
        # from the other. The old single query swallowed that error and
        # silently returned False for everyone.
        for column in ("manager_id", "leave_manager_id"):
            try:
                reports = (
                    supabase_admin.table("employees")
                    .select("id")
                    .eq(column, employee["id"])
                    .limit(1)
                    .execute()
                )
                if reports.data:
                    is_reporting_manager = True
                    break
            except Exception as e:
                logger.error(
                    f"Failed to check reporting-manager status via {column}: {e}"
                )

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
        # Never expose the internal placeholder login email -- an employee
        # created without an email just has a blank one here.
        "email": employee.get("email")
        or (None if is_placeholder_email(auth_user.email) else auth_user.email),
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
            "working_location": employee.get("working_location"),
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
            # Drives whether the frontend shows the "Check in from
            # meeting/site" button at all — see SKILL/README notes in
            # sql/030.sql. False for everyone until HR enables it
            # per-employee.
            "outdoor_checkin_enabled": bool(employee.get("outdoor_checkin_enabled")),
            "is_reporting_manager": is_reporting_manager,
        },
    }
