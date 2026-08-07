"""
Create a Super Admin login.

Why this is needed: /auth/login (app/auth/services.login_user) checks
credentials against Supabase Auth's own `auth.users` table -- that's
separate from this project's `employees` / `user_profiles` SQL tables.
The seed SQL (sql/001_schema.sql) inserts the *role* 'SUPER ADMIN', but
never creates an actual login for it. This script does three steps:

  1. Creates a real Supabase Auth user (via the admin API, using the
     service-role key already in .env) with the email/password you pass.
  2. Creates (or reuses) a matching row in `employees` with a fixed
     employee code, since /auth/login now authenticates by employee
     code, not email (app/auth/services.login_user resolves the code to
     an email via app/core/helpers/employee_helper.get_employee_by_code,
     which only looks in `employees` -- a Super Admin with no row there
     could never be looked up by code, even with the right password).
  3. Inserts/updates the matching row in `user_profiles`, linked to
     both the 'SUPER ADMIN' role and that `employees` row, so
     GET /auth/me resolves it correctly.

Run from the backend project root (same folder as requirement.txt):

    python scripts/create_super_admin.py --email admin@akrobat.sg --password ChangeMe123!

Then log in on the frontend with the employee code printed at the end
(default AKR-SA-0001) and that password -- NOT the email.
"""

import argparse
import sys
from pathlib import Path

# so `app.core.*` imports resolve when run as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import supabase_admin  # noqa: E402

# Fixed employee code for the one Super Admin login. Not run through
# generate_employee_id() (app/core/helpers/employee_helper.py) since
# that derives its prefix from a department/designation, neither of
# which applies to Super Admin.
DEFAULT_EMPLOYEE_CODE = "AKR-SA-0001"


def _ensure_employee_row(email: str, employee_code: str, full_name: str | None):
    # Re-running this script for the same email must stay a no-op here
    # too, mirroring the auth-user check below -- look up by email
    # first rather than blindly inserting a duplicate `employees` row.
    existing = (
        supabase_admin.table("employees")
        .select("id, employee_id")
        .eq("email", email)
        .maybe_single()
        .execute()
    )

    if existing and existing.data:
        employee_id = existing.data["id"]
        print(
            f"Employee row already exists, reusing it: "
            f"{existing.data['employee_id']} ({employee_id})"
        )
        return employee_id, existing.data["employee_id"]

    # employee_id (the code) is unique -- if AKR-SA-0001 is somehow
    # already taken by someone else, fail loudly rather than silently
    # picking a different code the operator didn't ask for.
    code_taken = (
        supabase_admin.table("employees")
        .select("id")
        .eq("employee_id", employee_code)
        .maybe_single()
        .execute()
    )
    if code_taken and code_taken.data:
        print(
            f"ERROR: employee code {employee_code} is already in use by a "
            "different employee. Pass a different --employee-code."
        )
        sys.exit(1)

    created = (
        supabase_admin.table("employees")
        .insert(
            {
                "employee_id": employee_code,
                "full_name": full_name or "Super Admin",
                "email": email,
                "employment_status": "Active",
            }
        )
        .execute()
    )
    employee_row = created.data[0]
    print(f"Created employee row: {employee_row['employee_id']} ({employee_row['id']})")
    return employee_row["id"], employee_row["employee_id"]


def create_super_admin(
    email: str,
    password: str,
    full_name: str | None = None,
    employee_code: str = DEFAULT_EMPLOYEE_CODE,
):
    # 1. Look up the SUPER ADMIN role (already seeded by sql/001_schema.sql)
    role_res = (
        supabase_admin.table("roles")
        .select("id, role_name")
        .eq("role_name", "SUPER ADMIN")
        .maybe_single()
        .execute()
    )
    if not role_res or not role_res.data:
        print("ERROR: 'SUPER ADMIN' role not found. Run sql/001_schema.sql first.")
        sys.exit(1)
    role_id = role_res.data["id"]

    # 2. Check first (not try/except-after-fail) so re-running this script
    # for the same email is always a no-op on the auth side -- never a
    # second/duplicate login for the same person.
    users = supabase_admin.auth.admin.list_users()
    existing = next(
        (u for u in users if (u.email or "").lower() == email.lower()), None
    )

    if existing:
        auth_user_id = existing.id
        print(f"Auth user already exists, reusing it: {email} ({auth_user_id})")
    else:
        created = supabase_admin.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,  # skip email verification for this account
            }
        )
        auth_user_id = created.user.id
        print(f"Created auth user: {email} ({auth_user_id})")

    # 3. Create/reuse the `employees` row -- this is what makes the
    # account resolvable by employee code at login (see module docstring).
    employee_row_id, resolved_code = _ensure_employee_row(
        email, employee_code, full_name
    )

    # 4. Link it in user_profiles with the SUPER ADMIN role + the
    # employees row from step 3 (previously employee_id was left null
    # here, which is what broke code-based login -- see login_user() /
    # get_employee_by_code() in app/auth/services.py and
    # app/core/helpers/employee_helper.py).
    profile_res = (
        supabase_admin.table("user_profiles")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )

    if profile_res and profile_res.data:
        supabase_admin.table("user_profiles").update(
            {"role_id": role_id, "employee_id": employee_row_id, "is_active": True}
        ).eq("auth_user_id", auth_user_id).execute()
        print("Updated existing user_profiles row -> role set to SUPER ADMIN.")
    else:
        supabase_admin.table("user_profiles").insert(
            {
                "auth_user_id": auth_user_id,
                "role_id": role_id,
                "employee_id": employee_row_id,
                "is_active": True,
            }
        ).execute()
        print("Created user_profiles row -> role set to SUPER ADMIN.")

    print("\nDone. Log in with:")
    print(f"  employee code: {resolved_code}")
    print(f"  password:      {password}")
    print(
        "\n(Login is by employee code, not email -- the email above is only "
        "what's on file for this account.)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a Super Admin login")
    parser.add_argument(
        "--email",
        default="IT@akrobat.com.sg",
        help="Defaults to IT@akrobat.com.sg -- the one fixed Super Admin account. "
        "Re-running this script with the same email is safe: it will not "
        "create a duplicate login, it just re-confirms the role.",
    )
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--full-name",
        default=None,
        help="Full name for the `employees` row. Defaults to 'Super Admin'.",
    )
    parser.add_argument(
        "--employee-code",
        default=DEFAULT_EMPLOYEE_CODE,
        help=f"Employee code used to log in (defaults to {DEFAULT_EMPLOYEE_CODE}).",
    )
    args = parser.parse_args()

    create_super_admin(args.email, args.password, args.full_name, args.employee_code)
