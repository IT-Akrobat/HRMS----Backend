"""
Create a Super Admin login.

Why this is needed: /auth/login (app/auth/services.login_user) checks
credentials against Supabase Auth's own `auth.users` table -- that's
separate from this project's `employees` / `user_profiles` SQL tables.
The seed SQL (sql/001_schema.sql) inserts the *role* 'SUPER ADMIN', but
never creates an actual login for it. This script does both steps:

  1. Creates a real Supabase Auth user (via the admin API, using the
     service-role key already in .env) with the email/password you pass.
  2. Inserts the matching row in `user_profiles`, linked to the
     'SUPER ADMIN' role, so GET /auth/me resolves it correctly.

Run from the backend project root (same folder as requirement.txt):

    python scripts/create_super_admin.py --email admin@akrobat.sg --password ChangeMe123!

Then log in on the frontend with that email/password.
"""

import argparse
import sys
from pathlib import Path

# so `app.core.*` imports resolve when run as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import supabase_admin  # noqa: E402


def create_super_admin(email: str, password: str, full_name: str | None = None):
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
    existing = next((u for u in users if (u.email or "").lower() == email.lower()), None)

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

    # 3. Link it in user_profiles with the SUPER ADMIN role
    profile_res = (
        supabase_admin.table("user_profiles")
        .select("id")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )

    if profile_res and profile_res.data:
        supabase_admin.table("user_profiles").update(
            {"role_id": role_id, "is_active": True}
        ).eq("auth_user_id", auth_user_id).execute()
        print("Updated existing user_profiles row -> role set to SUPER ADMIN.")
    else:
        supabase_admin.table("user_profiles").insert(
            {"auth_user_id": auth_user_id, "role_id": role_id, "is_active": True}
        ).execute()
        print("Created user_profiles row -> role set to SUPER ADMIN.")

    print("\nDone. Log in with:")
    print(f"  email:    {email}")
    print(f"  password: {password}")
    print(
        "\nNote: no `employees` row was linked, so `full_name` / department will be "
        "empty on /auth/me until you link one -- that's fine for testing login."
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
    args = parser.parse_args()

    create_super_admin(args.email, args.password)
