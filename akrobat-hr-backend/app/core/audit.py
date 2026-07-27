"""
Single, consistent audit-logging entry point for the whole backend.

Previously there were two separate helpers (app/core/helpers/audit_helper.py
and app/audit_logs/services.create_audit_log) with slightly different
signatures. This module replaces both. The old ones are kept as thin
wrappers for backward compatibility so existing imports don't break, but
new code should call `record_audit_log` from here.

Every meaningful write (create/update/delete/approve/reject/...) anywhere
in the system should call this function. It never raises — a failure to
write an audit log must not break the request that triggered it.
"""

from typing import Any, Optional

from fastapi import Request

from app.core.database import supabase_admin
from app.core.logger import logger


def _diff(old_values: Optional[dict], new_values: Optional[dict]) -> Optional[dict]:
    """Return only the fields that actually changed, for a compact audit trail."""

    if old_values is None or new_values is None:
        return new_values

    changed = {}

    for key, new_val in new_values.items():
        old_val = old_values.get(key)

        if old_val != new_val:
            changed[key] = {"old": old_val, "new": new_val}

    return changed or None


def _resolve_employee_id(identifier: Optional[str]) -> Optional[str]:
    """
    `audit_logs.employee_id` is a foreign key to `employees(id)` — but
    every caller of `record_audit_log` passes `performed_by` as the
    Supabase *auth* user id (`current_user.id` / `user.id` from
    `get_current_user`), which lives in a different id space entirely.
    Inserting that value directly violates the FK, the insert fails, and
    since this function never raises, the failure was previously
    swallowed silently — audit rows for Payroll/Leaves/Documents writes
    were not actually being recorded.

    This resolves an auth user id to its linked `employees.id` via
    `user_profiles` before writing. If `identifier` doesn't resolve (e.g.
    it's already an employees.id from an older/direct caller, or there's
    no linked profile), it's used as-is so existing valid callers are
    unaffected.
    """

    if not identifier:
        return None

    try:
        from app.core.helpers.employee_helper import get_employee_id_for_auth_user

        employee_id = get_employee_id_for_auth_user(identifier)

        return employee_id or identifier

    except Exception:
        return identifier


def record_audit_log(
    *,
    module: str,
    action: str,
    performed_by: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    record_id: Optional[str] = None,
    description: Optional[str] = None,
    old_values: Optional[dict[str, Any]] = None,
    new_values: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
):
    """
    Write one audit log row. Safe to call from anywhere; never raises.

    module            e.g. "EMPLOYEE", "ATTENDANCE", "LEAVE", "PAYROLL"
    action             e.g. "CREATE", "UPDATE", "DELETE", "APPROVE", "REJECT"
    performed_by       auth/employee id of the actor (who did it)
    target_employee_id which employee record this action is about, if any
    record_id          id of the row that was affected
    old_values/new_values  used to compute a field-level diff automatically
    request            pass the FastAPI Request to auto-capture IP + user agent
    """

    try:
        resolved_employee_id = _resolve_employee_id(performed_by)

        payload = {
            "employee_id": resolved_employee_id,
            "action": action,
            "module": module,
            "record_id": str(record_id) if record_id else None,
            "description": description,
        }

        changes = _diff(old_values, new_values)

        details = {}

        if target_employee_id:
            details["target_employee_id"] = str(target_employee_id)

        if changes:
            details["changes"] = changes

        if details:
            # audit_logs.description is a free-text column in the current
            # schema; store structured details as JSON text so nothing is
            # lost until a dedicated `details jsonb` column is migrated in.
            import json

            payload["description"] = json.dumps(
                {"message": description, **details}, default=str
            )

        if request is not None:
            payload["ip_address"] = request.client.host if request.client else None
            payload["user_agent"] = request.headers.get("user-agent")

        # Some deployments still have the narrower audit_logs schema
        # (no ip_address/user_agent columns). Try the rich insert first,
        # then fall back to the minimal columns so logging never blocks
        # the request that triggered it.
        try:
            response = supabase_admin.table("audit_logs").insert(payload).execute()
            return response.data[0] if response.data else None
        except Exception:
            minimal_payload = {
                "employee_id": resolved_employee_id,
                "action": action,
                "module": module,
                "record_id": payload["record_id"],
            }
            response = supabase_admin.table("audit_logs").insert(minimal_payload).execute()
            return response.data[0] if response.data else None

    except Exception as e:
        logger.error(f"Audit log write failed | module={module} action={action} | {e}")
        return None


# ---------------------------------------------------------------------------
# Backward-compatible shims for existing call sites.
# ---------------------------------------------------------------------------


def create_audit_log(
    employee_id: Optional[str],
    action: str,
    module: str,
    record_id: Optional[str] = None,
    description: Optional[str] = None,
):
    """Kept for existing imports from app.core.helpers.audit_helper."""

    record_audit_log(
        module=module,
        action=action,
        performed_by=employee_id,
        record_id=record_id,
        description=description,
    )
