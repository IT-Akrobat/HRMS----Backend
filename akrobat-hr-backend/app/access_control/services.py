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


def is_locked(lockout_row: dict | None) -> bool:
    if not lockout_row or not lockout_row.get("locked_until"):
        return False

    locked_until = datetime.fromisoformat(lockout_row["locked_until"])
    return locked_until > datetime.now(timezone.utc)


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
# FORCE LOGOUT ALL -- revokes every admin's refresh tokens via the
# Supabase GoTrue admin API. Done as a direct REST call (rather than
# supabase-py's auth.admin helpers) since the "revoke all sessions for a
# user" endpoint isn't wrapped consistently across supabase-py versions.
# =========================================================================


def force_logout_all_admins() -> dict:
    admin_roles = (
        supabase_admin.table("roles")
        .select("id")
        .in_("role_name", ["SUPER ADMIN", "HR ADMIN"])
        .execute()
    )
    role_ids = [r["id"] for r in (admin_roles.data or [])]

    if not role_ids:
        return {"signed_out": 0}

    profiles = (
        supabase_admin.table("user_profiles")
        .select("auth_user_id")
        .in_("role_id", role_ids)
        .execute()
    )
    auth_user_ids = [
        p["auth_user_id"] for p in (profiles.data or []) if p.get("auth_user_id")
    ]

    signed_out = 0
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
            except httpx.HTTPError:
                # Best-effort -- one unreachable/edge-case user shouldn't
                # stop the rest of the admins from being signed out.
                continue

    return {"signed_out": signed_out, "targeted": len(auth_user_ids)}
