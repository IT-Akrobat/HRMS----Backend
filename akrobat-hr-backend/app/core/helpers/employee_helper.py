import random
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
# GENERATE EMPLOYEE ID (company + department + designation based)
# ==========================================
#
# Employee codes look like AKR-HR-EXE-0001 -- COMPANY_PREFIX, then the
# department code (departments.department_code, e.g. HR/FIN/OPS -- see
# sql/001_schema.sql seed data), then a short designation code derived
# from designation_name (designations has no dedicated code column, so
# initials are derived on the fly, e.g. "HR Executive" -> "HE",
# "Manager" -> "MAN"), then a running numeric sequence zero-padded to 4
# digits. The designation segment is only appended when the employee
# has a designation -- an employee with just a department still gets
# AKR-HR-0001. The sequence is scoped to everything already sharing the
# same full prefix and falls forward on a collision (e.g. a deleted
# employee freed up a lower number) so this can never return a
# duplicate code.


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

    dept_code = _department_prefix(department_id)
    desig_code = _designation_prefix(designation_id)

    prefix = (
        f"{COMPANY_PREFIX}-{dept_code}-{desig_code}"
        if desig_code
        else f"{COMPANY_PREFIX}-{dept_code}"
    )

    # Every employee code that already starts with this exact
    # department/designation prefix -- used to work out the next free
    # sequence number.
    existing = (
        supabase_admin.table("employees")
        .select("employee_id")
        .ilike("employee_id", f"{prefix}-%")
        .execute()
    )

    existing_ids = {row["employee_id"] for row in (existing.data or [])}

    sequence = len(existing_ids) + 1

    while True:

        employee_id = f"{prefix}-{sequence:04d}"

        if employee_id not in existing_ids:
            return employee_id

        sequence += 1


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
# LOOKUP EMAIL BY EMPLOYEE CODE (for login)
# ==========================================
#
# The frontend login form now collects the human-readable employee code
# (e.g. HR-0001) instead of an email address. Supabase Auth itself still
# authenticates by email under the hood, so this resolves
# employee_code -> the email on file for that employee, which
# app/auth/services.py then hands to supabase.auth.sign_in_with_password.
# Returns None (never raises) if the code doesn't exist, so the caller
# can respond with a generic "invalid credentials" instead of
# confirming/denying that a given employee code exists.
def get_email_for_employee_code(employee_code: str) -> str | None:

    if not employee_code:
        return None

    response = (
        supabase_admin.table("employees")
        .select("email")
        .eq("employee_id", employee_code.strip().upper())
        .maybe_single()
        .execute()
    )

    if not response or not response.data:
        return None

    return response.data.get("email")


# ==========================================
# VALIDATE COMPANY EMAIL
# ==========================================


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


def resolve_default_shift_id(designation_id: str | None) -> str | None:
    """
    "When creating a user, their working hours should be mentioned" —
    every designation is seeded with a `default_shift_id` (see
    sql/014_designation_shifts_and_site_visits.sql) matching the real
    Attendance Info doc (Office / Operation Site / Inspection Site /
    Work Shop hours). Called by create_employee() ONLY when the caller
    didn't explicitly pass a shift_id, so HR can still hand-pick a
    different shift (e.g. the 9-6 Office variant) per employee — this
    is a suggestion/default, not a hard rule.
    """

    if not designation_id:
        return None

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
    Ids of every employee whose designation sits under an
    INSPECTION*/OPERATION* department — the staff who visit multiple
    sites in a day and therefore get the Site Visits UI, as opposed to a
    single fixed office/desk. Derived from department rather than a
    dedicated boolean column, since department is already the source of
    truth (see sql/014_designation_shifts_and_site_visits.sql) and the
    set of "field" departments may grow later without a schema change.
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

        desig_response = (
            supabase_admin.table("designations")
            .select("id")
            .in_("department_id", field_dept_ids)
            .execute()
        )
        field_desig_ids = [d["id"] for d in (desig_response.data or [])]

        if not field_desig_ids:
            return set()

        emp_response = (
            supabase_admin.table("employees")
            .select("id")
            .in_("designation_id", field_desig_ids)
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