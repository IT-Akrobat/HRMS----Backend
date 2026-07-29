import ipaddress
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException

from app.core.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from app.core.database import supabase_admin

# =========================================================================
# SETTINGS (singleton row, same shape as app/settings/services.py)
# =========================================================================


def get_access_control_settings() -> dict:
    try:
        response = (
            supabase_admin.table("access_control_settings")
            .select("*")
            .limit(1)
            .execute()
        )

        if not response.data:
            raise HTTPException(
                status_code=500,
                detail="Access control settings row missing -- run sql/017_access_control_settings.sql",
            )

        return response.data[0]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def update_access_control_settings(data: dict) -> dict:
    try:
        if "allowed_ip_ranges" in data and data["allowed_ip_ranges"] is not None:
            for cidr in data["allowed_ip_ranges"]:
                try:
                    ipaddress.ip_network(cidr, strict=False)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"'{cidr}' isn't a valid IP or CIDR range.",
                    )

        existing = (
            supabase_admin.table("access_control_settings")
            .select("id")
            .limit(1)
            .execute()
        )

        if not existing.data:
            raise HTTPException(
                status_code=404, detail="Access control settings not found"
            )

        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        response = (
            supabase_admin.table("access_control_settings")
            .update(data)
            .eq("id", existing.data[0]["id"])
            .execute()
        )

        return response.data[0]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# LOCKOUT -- consumed by app/auth/services.py::login_user
# =========================================================================


def get_lockout_status(employee_id: str) -> dict | None:
    """Returns the login_lockouts row for this employee, or None if
    they've never failed a login."""

    response = (
        supabase_admin.table("login_lockouts")
        .select("*")
        .eq("employee_id", employee_id)
        .maybe_single()
        .execute()
    )

    return response.data if response else None


def _parse_ts(value: str) -> datetime:
    # Postgrest sometimes returns a trailing 'Z' instead of '+00:00';
    # datetime.fromisoformat() only accepts the latter on Python < 3.11.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_locked(lockout_row: dict | None) -> bool:
    if not lockout_row or not lockout_row.get("locked_until"):
        return False

    return _parse_ts(lockout_row["locked_until"]) > datetime.now(timezone.utc)


def register_failed_attempt(
    employee_id: str, lockout_attempts: int, lockout_minutes: int
):
    """Increments the failed-attempt counter and locks the account once
    it reaches the configured threshold."""

    existing = get_lockout_status(employee_id)
    attempts = (existing.get("failed_attempts", 0) if existing else 0) + 1

    payload = {
        "employee_id": employee_id,
        "failed_attempts": attempts,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if attempts >= lockout_attempts:
        payload["locked_until"] = (
            datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
        ).isoformat()

    supabase_admin.table("login_lockouts").upsert(
        payload, on_conflict="employee_id"
    ).execute()

    return attempts


def reset_lockout(employee_id: str):
    supabase_admin.table("login_lockouts").upsert(
        {
            "employee_id": employee_id,
            "failed_attempts": 0,
            "locked_until": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="employee_id",
    ).execute()


# =========================================================================
# IP RESTRICTION -- consumed by app/auth/services.py::login_user
# =========================================================================


def is_ip_allowed(client_ip: str | None, allowed_ranges: list[str]) -> bool:
    if not allowed_ranges:
        # Restriction is on but no ranges configured yet -- fail open
        # rather than locking every admin out with an empty allowlist.
        return True

    if not client_ip:
        return False

    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for cidr in allowed_ranges:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue

    return False


# =========================================================================
# PASSWORD EXPIRY -- consumed by app/auth/services.py::login_user and
# ::change_password. Backed by user_profiles.password_changed_at (see
# sql/018_password_expiry_tracking.sql).
# =========================================================================


def get_password_changed_at(employee_id: str) -> datetime | None:
    response = (
        supabase_admin.table("user_profiles")
        .select("password_changed_at")
        .eq("employee_id", employee_id)
        .maybe_single()
        .execute()
    )

    if (
        not response
        or not response.data
        or not response.data.get("password_changed_at")
    ):
        return None

    return _parse_ts(response.data["password_changed_at"])


def is_password_expired(password_changed_at: datetime | None, expiry_days: int) -> bool:
    if not expiry_days or expiry_days <= 0:
        return False  # 0/unset = expiry disabled

    if not password_changed_at:
        return False  # no record yet -- don't lock people out over missing data

    age = datetime.now(timezone.utc) - password_changed_at
    return age.days >= expiry_days


def touch_password_changed_at(auth_user_id: str):
    """Call this whenever a password is actually changed (see
    app/auth/services.py::change_password) so the expiry clock resets."""

    supabase_admin.table("user_profiles").update(
        {"password_changed_at": datetime.now(timezone.utc).isoformat()}
    ).eq("auth_user_id", auth_user_id).execute()


# =========================================================================
# FORCE LOGOUT -- revokes sessions for every non-SUPER-ADMIN account
# (employee, HR admin, manager, team leader, etc.) via the Supabase
# GoTrue admin API. Super Admins are deliberately excluded -- the person
# clicking this button is a Super Admin and shouldn't sign themself, or
# any other Super Admin, out.
# =========================================================================


def force_logout_all_admins() -> dict:
    roles = supabase_admin.table("roles").select("id, role_name").execute()
    target_role_ids = [
        r["id"] for r in (roles.data or []) if r["role_name"] != "SUPER ADMIN"
    ]

    if not target_role_ids:
        return {"signed_out": 0, "targeted": 0, "errors": []}

    profiles = (
        supabase_admin.table("user_profiles")
        .select("auth_user_id")
        .in_("role_id", target_role_ids)
        .execute()
    )
    auth_user_ids = [
        p["auth_user_id"] for p in (profiles.data or []) if p.get("auth_user_id")
    ]

    signed_out = 0
    errors = []
    with httpx.Client(timeout=10) as client:
        for uid in auth_user_ids:
            try:
                res = client.post(
                    f"{SUPABASE_URL}/auth/v1/admin/users/{uid}/logout",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    },
                    params={"scope": "global"},
                )
                if res.status_code < 300:
                    signed_out += 1
                else:
                    # Surfaced rather than swallowed -- a silent 0/2 with
                    # no reason is undebuggable from the frontend. Common
                    # causes: SUPABASE_SERVICE_ROLE_KEY isn't actually the
                    # service-role key (401), or this GoTrue version
                    # doesn't expose this admin route the same way (404).
                    errors.append(f"{uid}: HTTP {res.status_code} — {res.text[:200]}")
            except httpx.HTTPError as e:
                errors.append(f"{uid}: {e}")

    return {
        "signed_out": signed_out,
        "targeted": len(auth_user_ids),
        "errors": errors,
    }
