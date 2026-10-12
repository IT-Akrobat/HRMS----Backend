"""
Change a Super Admin's login username.

Put in  scripts/  and run from the backend root:

    python scripts/change_super_admin_username.py --current "Super Admin" --new "akrobat_admin"

--current can be the employee code (AKR-SA-0001), the current username or the full name.
Add --also-full-name to rename the display name too.
Password does not change. Login = the new username.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import supabase_admin  # noqa: E402


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def find_employee(key: str):
    for col in ("employee_id", "username", "full_name"):
        rows = (
            supabase_admin.table("employees")
            .select("id, employee_id, full_name, username")
            .ilike(col, key)
            .execute()
            .data
            or []
        )
        if rows:
            return rows
    return []


def is_super_admin(emp_id: str) -> bool:
    rows = (
        supabase_admin.table("user_profiles")
        .select("roles!inner(role_name)")
        .eq("employee_id", emp_id)
        .eq("roles.role_name", "SUPER ADMIN")
        .execute()
        .data
        or []
    )
    return bool(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--current", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--also-full-name", action="store_true")
    a = p.parse_args()

    new = " ".join(a.new.split())
    if not new:
        die("New username is empty.")

    rows = find_employee(a.current.strip())
    if not rows:
        die(f"No employee found for '{a.current}'.")
    if len(rows) > 1:
        die("More than one match. Use the employee code (e.g. AKR-SA-0001).")
    emp = rows[0]

    if not is_super_admin(emp["id"]):
        die(f"{emp['employee_id']} is not a SUPER ADMIN. Nothing changed.")

    # new name must not clash with anyone else's username OR full name
    for col in ("username", "full_name"):
        for r in (
            supabase_admin.table("employees")
            .select("id")
            .ilike(col, new)
            .execute()
            .data
            or []
        ):
            if r["id"] != emp["id"]:
                die(f"'{new}' is already used as {col} by another employee.")

    update = {"username": new}
    if a.also_full_name:
        update["full_name"] = new

    supabase_admin.table("employees").update(update).eq("id", emp["id"]).execute()

    print(f"Updated {emp['employee_id']}")
    print(
        f"  old username : {emp.get('username') or '(none)'}  | full name: {emp['full_name']}"
    )
    print(f"  new username : {new}")
    print("Log in with the new username and the SAME password.")
    if not a.also_full_name:
        print(
            f"(Old full name '{emp['full_name']}' still works as a login too, unless you re-run with --also-full-name.)"
        )


if __name__ == "__main__":
    main()
