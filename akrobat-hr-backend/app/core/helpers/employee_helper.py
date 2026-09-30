import random
import re
import secrets
import string

from app.core.database import supabase_admin
from app.core.exceptions import (
    bad_request,
    conflict,
    not_found,
)
from app.core.constants import *

ALLOWED_DOMAIN = "akrobat.com.sg"

# Fallback prefix used when an employee is created without a department
# (department_id is optional on EmployeeCreate) or when the department
# row has no department_code set for some reason.
DEFAULT_EMPLOYEE_PREFIX = "EMP"

# Fixed company prefix every employee code starts with.
COMPANY_PREFIX = "AKR"


# ==========================================
# GENERATE EMPLOYEE ID (short running number)
# ==========================================
#
# Employee codes are now short: COMPANY_PREFIX + a running number
# zero-padded to 4 digits -- AKR-0001, AKR-0002, ... The department and
# designation are no longer part of the code, so it never needs to change
# when someone is moved or promoted. Older codes such as
# AKR-HR-EXE-0001 stay exactly as they are; only new employees get the
# short format. The next number is one more than the highest existing
# AKR-<number> code, so it can never collide with an existing code.


def _department_prefix(department_id: str | None) -> str:

    if not department_id:
        return DEFAULT_EMPLOYEE_PREFIX

    response = (
        supabase_admin.table("departments")
        .select("department_code")
        .eq("id", department_id)
        .maybe_single()
        .execute()
    )

    code = (response.data or {}).get("department_code") if response else None

    if not code:
        return DEFAULT_EMPLOYEE_PREFIX

    return code.strip().upper()


def _designation_prefix(designation_id: str | None) -> str | None:

    if not designation_id:
        return None

    response = (
        supabase_admin.table("designations")
        .select("designation_name")
        .eq("id", designation_id)
        .maybe_single()
        .execute()
    )

    name = (response.data or {}).get("designation_name") if response else None

    if not name:
        return None

    words = name.strip().upper().split()

    # Single-word designation ("MANAGER") -> first 3 letters ("MAN").
    # Multi-word designation ("HR EXECUTIVE") -> initials ("HE").
    if len(words) == 1:
        return words[0][:3]

    return "".join(word[0] for word in words if word)[:4]


def generate_employee_id(
    department_id: str | None = None,
    designation_id: str | None = None,
) -> str:
    # department_id / designation_id are accepted only so existing
    # callers (create_employee, the code preview) keep working -- they
    # no longer affect the code.

    pattern = re.compile(rf"^{re.escape(COMPANY_PREFIX)}-(\d+)$", re.IGNORECASE)

    highest = 0
    start, page_size = 0, 1000

    while True:
        response = (
            supabase_admin.table("employees")
            .select("employee_id")
            .ilike("employee_id", f"{COMPANY_PREFIX}-%")
            .range(start, start + page_size - 1)
            .execute()
        )

        rows = response.data or []

        for row in rows:
            match = pattern.match(row.get("employee_id") or "")
            if match:
                highest = max(highest, int(match.group(1)))

        if len(rows) < page_size:
            break

        start += page_size

    return f"{COMPANY_PREFIX}-{highest + 1:04d}"


# ==========================================
# GENERATE TEMPORARY PASSWORD
# ==========================================
#
# Replaces the old flow where HR typed in the new employee's password
# by hand. A strong random password is generated here instead, used to
# create the Supabase auth user, and returned once in the API response
# (see create_employee in app/employees/services.py) so HR can share it
# with the employee through whatever secure channel they use. It is
# never stored in plaintext anywhere -- Supabase only keeps the hash.
def generate_temp_password(length: int = 10) -> str:

    if length < 8:
        length = 8

    letters_upper = string.ascii_uppercase
    letters_lower = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%*"

    # Guarantee at least one of each character class so the password
    # always satisfies typical strength rules, then fill the rest
    # randomly and shuffle so the guaranteed characters aren't always
    # in the same position.
    password_chars = [
        secrets.choice(letters_upper),
        secrets.choice(letters_lower),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]

    remaining_pool = letters_upper + letters_lower + digits + symbols
    password_chars += [
        secrets.choice(remaining_pool) for _ in range(length - len(password_chars))
    ]

    secrets.SystemRandom().shuffle(password_chars)

    return "".join(password_chars)


# ==========================================
# PLACEHOLDER LOGIN EMAIL (employees created without an email)
# ==========================================
#
# Email is optional when creating a user. Supabase Auth still needs
# *some* email to create the login, so an employee created without one
# gets an internal placeholder address derived from the employee code.
# It is only ever stored on the Supabase Auth user -- employees.email
# stays NULL, so HR sees a blank email and can fill it in later
# (update_employee() then syncs the real address to Supabase Auth).
PLACEHOLDER_EMAIL_DOMAIN = "noemail.akrobat.local"


def placeholder_login_email(employee_code: str) -> str:
    return f"{employee_code.strip().lower()}@{PLACEHOLDER_EMAIL_DOMAIN}"


def is_placeholder_email(email: str | None) -> bool:
    return bool(email) and email.lower().endswith("@" + PLACEHOLDER_EMAIL_DOMAIN)


# ==========================================
# LOOKUP EMPLOYEE BY USERNAME (for login)
# ==========================================
#
# The login "username" is simply the employee's full name -- the same
# value HR types into the Name field when creating the user. It is short
# and easy to remember, unlike the generated employee code
# (AKR-HR-EXE-0001). Matching is case-insensitive and ignores extra
# spaces, so "priya  kumar" logs in as "Priya Kumar".
#
# Full names are only usable as usernames if they are unique, so
# create_employee()/update_employee() reject a name already in use (see
# username_taken below).


def normalize_username(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _like_escape(value: str) -> str:
    # Stop % and _ typed in a name from acting as wildcards.
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_employees_by_username(username: str) -> list[dict]:
    """All employees who log in as `username` (normally 0 or 1).

    An employee's login is their `username` column when HR set one
    (e.g. "SAKTHI"); employees with no username still log in with their
    full name, so existing accounts keep working.
    """

    wanted = normalize_username(username)

    if not wanted:
        return []

    pattern = _like_escape(wanted)
    select = "id, employee_id, email, full_name, username"

    by_username = (
        supabase_admin.table("employees")
        .select(select)
        .ilike("username", pattern)
        .execute()
    )
    by_name = (
        supabase_admin.table("employees")
        .select(select)
        .ilike("full_name", pattern)
        .execute()
    )

    found: dict[str, dict] = {}

    for row in by_username.data or []:
        if normalize_username(row.get("username")) == wanted:
            found[row["id"]] = row

    for row in by_name.data or []:
        # Full name only counts as a login when no username is set.
        if (
            not row.get("username")
            and normalize_username(row.get("full_name")) == wanted
        ):
            found[row["id"]] = row

    return list(found.values())


def username_taken(full_name: str, exclude_employee_id: str | None = None) -> bool:
    return any(
        row["id"] != exclude_employee_id
        for row in find_employees_by_username(full_name)
    )


# ==========================================
# VALIDATE COMPANY EMAIL (unused)
# ==========================================
#
# No longer called from create_employee()/update_employee() -- the
# @akrobat.com.sg-only restriction on user-entered emails was removed.
# Any syntactically valid email is now accepted there (see
# app/core/validators.validate_email). Left here only because
# ALLOWED_DOMAIN below is still used for the auto-generated placeholder
# login email when HR leaves the email field blank.


def validate_company_email(email: str):

    if not email:
        bad_request("Email is required.")

    if not email.lower().endswith(f"@{ALLOWED_DOMAIN}"):
        bad_request(f"Only @{ALLOWED_DOMAIN} email is allowed.")


# ==========================================
# CHECK EMAIL EXISTS
# ==========================================


def check_email_exists(email: str, exclude_employee_id: str | None = None):

    query = supabase_admin.table("employees").select("id").eq("email", email)

    if exclude_employee_id:
        query = query.neq("id", exclude_employee_id)

    response = query.execute()

    if response.data:
        conflict("Email already exists.")


# ==========================================
# VALIDATE FOREIGN KEY
# ==========================================


def validate_reference(
    table_name: str,
    record_id: str | None,
    field_name: str,
):

    if not record_id:
        return

    response = (
        supabase_admin.table(table_name).select("id").eq("id", record_id).execute()
    )

    if not response.data:
        not_found(f"{field_name} not found.")


# ==========================================
# RESOLVE DEFAULT SHIFT FROM DESIGNATION
# ==========================================


# Operation "PROJECT MANAGER" works from the office when the login role is
# MANAGER, so they get Office hours instead of the Operation Site hours
# every other Operation designation (and a PROJECT MANAGER with the
# EMPLOYEE role) keeps.
MANAGER_OFFICE_SHIFT_NAME = "OFFICE - WEEKDAY (8:30-5:30)"


def is_operation_project_manager(designation_id: str) -> bool:
    """True if the designation is PROJECT MANAGER under the OPERATION* department."""

    response = (
        supabase_admin.table("designations")
        .select("designation_name, departments(department_name)")
        .eq("id", designation_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        return False

    designation_name = (response.data.get("designation_name") or "").strip().upper()
    department = response.data.get("departments") or {}
    department_name = (department.get("department_name") or "").strip().upper()

    return designation_name == "PROJECT MANAGER" and department_name.startswith(
        "OPERATION"
    )


# Everyone in the OPERATION department works EVERY Saturday, 8:00 AM - 3:30 PM
# (shift row "OPERATION SITE - SATURDAY", see sql/033.sql). The "Alternate
# Saturday (1st & 3rd)" option does not apply to them.
OPERATION_SATURDAY_AREA = "OPERATION SITE"


def is_operation_department_name(department_name: str | None) -> bool:
    return (department_name or "").strip().upper().startswith("OPERATION")


def is_project_manager_designation_name(designation_name: str | None) -> bool:
    return "PROJECT MANAGER" in (designation_name or "").strip().upper()


def is_operation_every_saturday_name(
    department_name: str | None, designation_name: str | None
) -> bool:
    """
    Operation staff who work EVERY Saturday (no alternate-Saturday option).
    Operation PROJECT MANAGER is the exception: they keep the Works Saturdays
    Yes/No + Alternate Saturday (1st & 3rd) options like other departments.
    """
    return is_operation_department_name(
        department_name
    ) and not is_project_manager_designation_name(designation_name)


def is_operation_every_saturday(
    department_id: str | None, designation_id: str | None
) -> bool:
    """ID-based version of is_operation_every_saturday_name()."""

    if not is_operation_department_id(department_id):
        return False

    if not designation_id:
        return True

    response = (
        supabase_admin.table("designations")
        .select("designation_name")
        .eq("id", str(designation_id))
        .maybe_single()
        .execute()
    )
    name = response.data.get("designation_name") if response and response.data else None
    return not is_project_manager_designation_name(name)


def is_operation_department_id(department_id: str | None) -> bool:
    """True if `department_id` is the OPERATION* department."""

    if not department_id:
        return False

    response = (
        supabase_admin.table("departments")
        .select("department_name")
        .eq("id", str(department_id))
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        return False

    return is_operation_department_name(response.data.get("department_name"))


def _is_manager_role(role_id: str | None) -> bool:
    if not role_id:
        return False

    response = (
        supabase_admin.table("roles")
        .select("role_name")
        .eq("id", str(role_id))
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        return False

    return (response.data.get("role_name") or "").strip().upper() == "MANAGER"


def resolve_default_shift_id(
    designation_id: str | None, role_id: str | None = None
) -> str | None:
    """
    "When creating a user, their working hours should be mentioned" —
    every designation is seeded with a `default_shift_id` (see
    sql/014_designation_shifts_and_site_visits.sql) matching the real
    Attendance Info doc (Office / Operation Site / Inspection Site /
    Work Shop hours). Called by create_employee() ONLY when the caller
    didn't explicitly pass a shift_id, so HR can still hand-pick a
    different shift (e.g. the 9-6 Office variant) per employee — this
    is a suggestion/default, not a hard rule.

    Exception: Operation > PROJECT MANAGER with the MANAGER role gets
    Office hours (MANAGER_OFFICE_SHIFT_NAME). Same designation with the
    EMPLOYEE role (or any other role) still gets the designation's
    normal Operation Site default.
    """

    if not designation_id:
        return None

    if is_operation_project_manager(designation_id) and _is_manager_role(role_id):
        shift_response = (
            supabase_admin.table("shifts")
            .select("id")
            .eq("shift_name", MANAGER_OFFICE_SHIFT_NAME)
            .maybe_single()
            .execute()
        )

        if shift_response and shift_response.data:
            return shift_response.data["id"]

    response = (
        supabase_admin.table("designations")
        .select("default_shift_id")
        .eq("id", designation_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        return None

    return response.data.get("default_shift_id")


# ==========================================
# GET EMPLOYEE
# ==========================================


def get_employee_or_404(employee_id: str):

    response = (
        supabase_admin.table("employees")
        .select("*")
        .eq("id", employee_id)
        .single()
        .execute()
    )

    if not response.data:
        not_found("Employee not found.")

    return response.data


# ==========================================
# GET EMPLOYEE ID FOR AUTH USER
# ==========================================


def get_employee_id_for_auth_user(auth_user_id: str) -> str | None:
    """
    Reverse lookup of get_user_profile: given the Supabase auth user id
    (what `get_current_user` returns as `user.id`), find the employee_id
    it's linked to. Used for self-service endpoints (e.g. "my payroll",
    "my documents") and for ownership checks — is this record the
    caller's own, regardless of what role/permission they hold.
    """

    response = (
        supabase_admin.table("user_profiles")
        .select("employee_id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        return None

    return response.data.get("employee_id")


# ==========================================
# GET ALL EMPLOYEE IDS FOR A GIVEN ROLE
# ==========================================


def get_employee_ids_for_role(role_name: str) -> list[str]:
    """
    Every employee (with a linked user_profiles row) whose role matches
    `role_name`, e.g. "SUPER ADMIN". Used to fan a notification out to
    everyone who holds a role, rather than a single hardcoded/derived
    person — see notify_employee() call sites in app/leaves/services.py.
    Returns [] (never raises) if the lookup fails for any reason, since
    callers treat notifications as best-effort.
    """

    try:
        response = (
            supabase_admin.table("user_profiles")
            .select("employee_id, roles!inner(role_name)")
            .eq("roles.role_name", role_name)
            .execute()
        )

        return [
            row["employee_id"]
            for row in (response.data or [])
            if row.get("employee_id")
        ]

    except Exception:
        return []


# ==========================================
# GET USER PROFILE
# ==========================================


# ==========================================
# MANAGER HIERARCHY (direct + indirect reports)
# ==========================================


def get_manager_chain(employee_id: str, max_depth: int = 10) -> list[str]:
    """
    Walks up `employees.manager_id` starting from `employee_id`, returning
    the ids of every manager above them (direct manager first). Stops at
    the top of the org chart or after `max_depth` hops (guards against a
    bad/circular manager_id causing an infinite loop).

    Used for ownership checks like "is this caller the direct or indirect
    manager of this employee" — e.g. leave/overtime approval — without
    hardcoding a role check.
    """

    chain: list[str] = []
    current_id = employee_id

    for _ in range(max_depth):
        response = (
            supabase_admin.table("employees")
            .select("manager_id")
            .eq("id", current_id)
            .maybe_single()
            .execute()
        )

        if not response or not response.data:
            break

        manager_id = response.data.get("manager_id")

        if not manager_id or manager_id in chain:
            break

        chain.append(manager_id)
        current_id = manager_id

    return chain


def is_manager_of(manager_employee_id: str | None, employee_id: str | None) -> bool:
    """True if manager_employee_id is the direct or indirect manager of employee_id."""

    if not manager_employee_id or not employee_id:
        return False

    return manager_employee_id in get_manager_chain(employee_id)


def get_all_report_ids(manager_employee_id: str, max_depth: int = 10) -> list[str]:
    """
    Returns the ids of every direct + indirect report of manager_employee_id
    (i.e. every employee whose manager chain includes manager_employee_id),
    via breadth-first traversal down the org chart.
    """

    all_report_ids: set[str] = set()
    frontier = [manager_employee_id]

    for _ in range(max_depth):
        if not frontier:
            break

        response = (
            supabase_admin.table("employees")
            .select("id")
            .in_("manager_id", frontier)
            .execute()
        )

        rows = response.data or []
        new_ids = [row["id"] for row in rows if row["id"] not in all_report_ids]

        if not new_ids:
            break

        all_report_ids.update(new_ids)
        frontier = new_ids

    return list(all_report_ids)


# ==========================================
# FIELD STAFF (multi-site Inspection / Operation employees)
# ==========================================


def get_field_employee_ids() -> set[str]:
    """
    Ids of every employee whose OWN department (employees.department_id)
    sits under an INSPECTION*/OPERATION* department — the staff who visit
    multiple sites in a day and therefore get the Site Visits UI, as
    opposed to a single fixed office/desk.

    NOTE: this used to be derived from the employee's DESIGNATION's
    department (designations.department_id) instead of the employee's own
    department field. That diverged from how the rest of the app already
    decides the exact same thing:
      - the frontend's own field-employee check (utils/employeeType.jsx's
        isFieldEmployee()) reads `user.department` straight off GET
        /auth/me — i.e. employees.department_id, not the designation's.
      - "Employee Details" (GET /employees/my-team) shows DEPARTMENT from
        that same employees.department_id column.

    In practice a shared designation can be seeded under a department that
    doesn't match every employee who holds it — e.g. "SENIOR QUANTITY
    SURVEYOR CUM LOGISTICS" is seeded under "QS" in
    sql/003_attendance_info_seed.sql — so an employee whose own department
    field says INSPECTION but who happens to hold that designation used to
    silently fail this check: excluded from the manager's "Team Members"
    assign-site picker, rejected by assign_site_to_employees /
    assign_site_to_team ("not in an Inspection/Operation role"), left out
    of get_team_site_visits_today — even though their own dashboard
    rendered the Site Visit card for them via the frontend's separate,
    employees.department_id-based check. Keying off employees.department_id
    here too makes "is this a field employee" agree everywhere, company-
    wide, off one column.

    Returns an empty set (never raises) — callers treat this as
    best-effort, same convention as get_employee_ids_for_role().
    """

    try:
        dept_response = (
            supabase_admin.table("departments").select("id, department_name").execute()
        )
        field_dept_ids = [
            d["id"]
            for d in (dept_response.data or [])
            if (d.get("department_name") or "")
            .upper()
            .startswith(("INSPECTION", "OPERATION"))
        ]

        if not field_dept_ids:
            return set()

        emp_response = (
            supabase_admin.table("employees")
            .select("id")
            .in_("department_id", field_dept_ids)
            .execute()
        )

        return {e["id"] for e in (emp_response.data or [])}

    except Exception:
        return set()


def is_field_employee(employee_id: str | None) -> bool:
    """Convenience single-employee check built on get_field_employee_ids()."""

    if not employee_id:
        return False

    return employee_id in get_field_employee_ids()


def get_user_profile(employee_id: str):

    response = (
        supabase_admin.table("user_profiles")
        .select("*")
        .eq("employee_id", employee_id)
        .execute()
    )

    return response.data[0] if response.data else None
