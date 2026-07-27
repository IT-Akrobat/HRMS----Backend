from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, internal_server_error
from app.core.audit import record_audit_log

audit_log_repo = SupabaseRepository("audit_logs")

AUDIT_LOG_SELECT = "*, employees(full_name, employee_id, profile_photo)"


# ==========================================
# CREATE LOG (manual/system entry — SUPER ADMIN only, requires MANAGE_AUDIT_LOGS)
# ==========================================
# Routed through record_audit_log (the same single write path every other
# module uses) instead of a separate raw insert — this also fixes the
# same employee_id/auth-id FK mismatch bug described in app/core/audit.py
# for this endpoint's own inserts.


def create_audit_log(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        record = record_audit_log(
            module=data.module,
            action=data.action,
            performed_by=auth_user_id,
            record_id=data.record_id,
            description=data.description,
            request=request,
        )

        return success_response(message="Audit log recorded successfully.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to record audit log.")


# ==========================================
# GET ALL LOGS (HR / Admin only — requires VIEW_AUDIT_LOGS)
# ==========================================


def get_audit_logs(page: int = 1, limit: int = 50):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 200), 1)
        end = start + max(min(limit, 200), 1) - 1

        records, total = audit_log_repo.list(
            select=AUDIT_LOG_SELECT,
            order_by="created_at",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Audit logs fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit logs.")


# ==========================================
# GET SINGLE LOG
# ==========================================


def get_audit_log(log_id: str):
    try:
        record = audit_log_repo.get_by_id_or_404(
            log_id, "Audit log not found.", select=AUDIT_LOG_SELECT
        )

        return success_response(message="Audit log fetched successfully.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit log.")


# ==========================================
# LOGS BY EMPLOYEE (actor) / MODULE / ACTION
# ==========================================


def get_employee_logs(employee_id: str, page: int = 1, limit: int = 50):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 200), 1)
        end = start + max(min(limit, 200), 1) - 1

        records, total = audit_log_repo.list(
            select=AUDIT_LOG_SELECT,
            filters={"employee_id": employee_id},
            order_by="created_at",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Audit logs fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit logs.")


def get_module_logs(module: str, page: int = 1, limit: int = 50):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 200), 1)
        end = start + max(min(limit, 200), 1) - 1

        records, total = audit_log_repo.list(
            select=AUDIT_LOG_SELECT,
            filters={"module": module},
            order_by="created_at",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Audit logs fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit logs.")


def get_action_logs(action: str, page: int = 1, limit: int = 50):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 200), 1)
        end = start + max(min(limit, 200), 1) - 1

        records, total = audit_log_repo.list(
            select=AUDIT_LOG_SELECT,
            filters={"action": action},
            order_by="created_at",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Audit logs fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit logs.")


# ==========================================
# LOGS BY DATE
# ==========================================


def get_logs_by_date(log_date: str):
    try:
        try:
            datetime.strptime(log_date, "%Y-%m-%d")
        except ValueError:
            bad_request("log_date must be in YYYY-MM-DD format.")

        from app.core.database import supabase_admin

        response = (
            supabase_admin.table("audit_logs")
            .select(AUDIT_LOG_SELECT)
            .gte("created_at", f"{log_date}T00:00:00")
            .lt("created_at", f"{log_date}T23:59:59")
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Audit logs fetched successfully.", data=response.data or []
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit logs.")


# ==========================================
# DELETE LOG (SUPER ADMIN only — requires MANAGE_AUDIT_LOGS)
# ==========================================
# Deleting audit trail entries undermines the point of an audit trail, so
# this is deliberately locked down tighter than every other delete route
# in the backend (no HR grant), and the deletion itself is recorded
# so there's a trace of who removed what.


def delete_audit_log(log_id: str, auth_user_id: str, request: Optional[Request] = None):
    try:
        existing = audit_log_repo.get_by_id_or_404(log_id, "Audit log not found.")

        audit_log_repo.delete(log_id)

        record_audit_log(
            module="AUDIT_LOGS",
            action="DELETE",
            performed_by=auth_user_id,
            record_id=log_id,
            description=f"Audit log deleted (was: {existing.get('module')}/{existing.get('action')})",
            old_values=existing,
            request=request,
        )

        return success_response(message="Audit log deleted successfully.")

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to delete audit log.")
