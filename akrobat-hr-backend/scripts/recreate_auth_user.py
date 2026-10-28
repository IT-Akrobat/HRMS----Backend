"""
Recreate a deleted Supabase Auth login for an existing employee.

When an auth user is deleted from Supabase -> Authentication -> Users, the
`employees` and `user_profiles` rows are NOT deleted (user_profiles.auth_user_id
has no foreign key to auth.users). The employee just can't log in any more,
because user_profiles.auth_user_id now points at an auth user that no longer
exists. This script creates a fresh auth user (same login email the app uses)
and re-points user_profiles.auth_user_id at it.

Run from the backend project root (where .env is):

    python scripts/recreate_auth_user.py --code AKR-0036 --password "Temp@12345"

Then log in with the employee code AKR-0036 and that password, and change it.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import supabase_admin  # noqa: E402
from app.core.helpers.employee_helper import placeholder_login_email  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="Employee code, e.g. AKR-0036")
    ap.add_argument("--password", required=True, help="New temporary password")
    args = ap.parse_args()

    emp = (
        supabase_admin.table("employees")
        .select("id, employee_id, full_name, email")
        .eq("employee_id", args.code.strip().upper())
        .maybe_single()
        .execute()
    )
    if not emp or not emp.data:
        sys.exit(f"No employee found with code {args.code}")
    emp = emp.data

    profile = (
        supabase_admin.table("user_profiles")
        .select("id, auth_user_id, is_active")
        .eq("employee_id", emp["id"])
        .maybe_single()
        .execute()
    )
    if not profile or not profile.data:
        sys.exit("No user_profiles row for this employee (role link is missing).")
    profile = profile.data

    # Refuse if the old auth user still exists -- nothing to recover then.
    try:
        existing = supabase_admin.auth.admin.get_user_by_id(profile["auth_user_id"])
        if existing and existing.user:
            sys.exit("The auth user still exists; use the normal reset-password flow.")
    except Exception:
        pass  # not found -> exactly the case we want to fix

    login_email = emp.get("email") or placeholder_login_email(emp["employee_id"])

    created = supabase_admin.auth.admin.create_user(
        {"email": login_email, "password": args.password, "email_confirm": True}
    )
    new_id = created.user.id

    supabase_admin.table("user_profiles").update(
        {"auth_user_id": new_id, "is_active": True}
    ).eq("id", profile["id"]).execute()

    print(f"Recovered {emp['full_name']} ({emp['employee_id']})")
    print(f"  login email : {login_email}")
    print(f"  new auth id : {new_id}")
    print("Login with the employee code and the password you passed.")


if __name__ == "__main__":
    main()
