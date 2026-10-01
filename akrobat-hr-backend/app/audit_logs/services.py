# from datetime import datetime, timezone
# from typing import Optional

# from fastapi import HTTPException, Request

# from app.core.repository import SupabaseRepository
# from app.core.responses import success_response
# from app.core.logger import logger
# from app.core.exceptions import bad_request, internal_server_error
# from app.core.audit import record_audit_log

# audit_log_repo = SupabaseRepository("audit_logs")

# AUDIT_LOG_SELECT = "*, employees(full_name, employee_id, profile_photo)"


# # ==========================================
# # CREATE LOG (manual/system entry — SUPER ADMIN only, requires MANAGE_AUDIT_LOGS)
# # ==========================================
# # Routed through record_audit_log (the same single write path every other
# # module uses) instead of a separate raw insert — this also fixes the
# # same employee_id/auth-id FK mismatch bug described in app/core/audit.py
# # for this endpoint's own inserts.


# def create_audit_log(auth_user_id: str, data, request: Optional[Request] = None):
#     try:
#         record = record_audit_log(
#             module=data.module,
#             action=data.action,
#             performed_by=auth_user_id,
#             record_id=data.record_id,
#             description=data.description,
#             request=request,
#         )

#         return success_response(message="Audit log recorded successfully.", data=record)

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to record audit log.")


# # ==========================================
# # GET ALL LOGS (HR / Admin only — requires VIEW_AUDIT_LOGS)
# # ==========================================


# def get_audit_logs(page: int = 1, limit: int = 50):
#     try:
#         start = (max(page, 1) - 1) * max(min(limit, 200), 1)
#         end = start + max(min(limit, 200), 1) - 1

#         records, total = audit_log_repo.list(
#             select=AUDIT_LOG_SELECT,
#             order_by="created_at",
#             ascending=False,
#             start=start,
#             end=end,
#         )

#         return success_response(
#             message="Audit logs fetched successfully.",
#             data={"records": records, "total": total, "page": page, "limit": limit},
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch audit logs.")


# # ==========================================
# # GET SINGLE LOG
# # ==========================================


# def get_audit_log(log_id: str):
#     try:
#         record = audit_log_repo.get_by_id_or_404(
#             log_id, "Audit log not found.", select=AUDIT_LOG_SELECT
#         )

#         return success_response(message="Audit log fetched successfully.", data=record)

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch audit log.")


# # ==========================================
# # LOGS BY EMPLOYEE (actor) / MODULE / ACTION
# # ==========================================


# def get_employee_logs(employee_id: str, page: int = 1, limit: int = 50):
#     try:
#         start = (max(page, 1) - 1) * max(min(limit, 200), 1)
#         end = start + max(min(limit, 200), 1) - 1

#         records, total = audit_log_repo.list(
#             select=AUDIT_LOG_SELECT,
#             filters={"employee_id": employee_id},
#             order_by="created_at",
#             ascending=False,
#             start=start,
#             end=end,
#         )

#         return success_response(
#             message="Audit logs fetched successfully.",
#             data={"records": records, "total": total, "page": page, "limit": limit},
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch audit logs.")


# def get_module_logs(module: str, page: int = 1, limit: int = 50):
#     try:
#         start = (max(page, 1) - 1) * max(min(limit, 200), 1)
#         end = start + max(min(limit, 200), 1) - 1

#         records, total = audit_log_repo.list(
#             select=AUDIT_LOG_SELECT,
#             filters={"module": module},
#             order_by="created_at",
#             ascending=False,
#             start=start,
#             end=end,
#         )

#         return success_response(
#             message="Audit logs fetched successfully.",
#             data={"records": records, "total": total, "page": page, "limit": limit},
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch audit logs.")


# def get_action_logs(action: str, page: int = 1, limit: int = 50):
#     try:
#         start = (max(page, 1) - 1) * max(min(limit, 200), 1)
#         end = start + max(min(limit, 200), 1) - 1

#         # `action` is usually a single value (CHECK_IN, CHECK_OUT, ...), but
#         # callers that need an OR across a small family of actions — e.g.
#         # the Audit Logs UI's "Site Visit" quick filter, which has to match
#         # both SITE_VISIT_ARRIVE and SITE_VISIT_DEPART — pass a
#         # comma-separated list instead. SupabaseRepository.list() only
#         # supports .eq() filters, so a multi-value list falls through to a
#         # raw .in_() query here rather than going through the repo.
#         actions = [a.strip() for a in action.split(",") if a.strip()]

#         if len(actions) > 1:
#             from app.core.database import supabase_admin

#             response = (
#                 supabase_admin.table("audit_logs")
#                 .select(AUDIT_LOG_SELECT, count="exact")
#                 .in_("action", actions)
#                 .order("created_at", desc=True)
#                 .range(start, end)
#                 .execute()
#             )
#             records, total = response.data or [], (response.count or 0)
#         else:
#             records, total = audit_log_repo.list(
#                 select=AUDIT_LOG_SELECT,
#                 filters={"action": action},
#                 order_by="created_at",
#                 ascending=False,
#                 start=start,
#                 end=end,
#             )

#         return success_response(
#             message="Audit logs fetched successfully.",
#             data={"records": records, "total": total, "page": page, "limit": limit},
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch audit logs.")


# # ==========================================
# # LOGS BY DATE
# # ==========================================


# def get_logs_by_date(log_date: str):
#     try:
#         try:
#             datetime.strptime(log_date, "%Y-%m-%d")
#         except ValueError:
#             bad_request("log_date must be in YYYY-MM-DD format.")

#         from app.core.database import supabase_admin

#         response = (
#             supabase_admin.table("audit_logs")
#             .select(AUDIT_LOG_SELECT)
#             .gte("created_at", f"{log_date}T00:00:00")
#             .lt("created_at", f"{log_date}T23:59:59")
#             .order("created_at", desc=True)
#             .execute()
#         )

#         return success_response(
#             message="Audit logs fetched successfully.", data=response.data or []
#         )

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to fetch audit logs.")


# # ==========================================
# # DELETE LOG (SUPER ADMIN only — requires MANAGE_AUDIT_LOGS)
# # ==========================================
# # Deleting audit trail entries undermines the point of an audit trail, so
# # this is deliberately locked down tighter than every other delete route
# # in the backend (no HR grant), and the deletion itself is recorded
# # so there's a trace of who removed what.


# def delete_audit_log(log_id: str, auth_user_id: str, request: Optional[Request] = None):
#     try:
#         existing = audit_log_repo.get_by_id_or_404(log_id, "Audit log not found.")

#         audit_log_repo.delete(log_id)

#         record_audit_log(
#             module="AUDIT_LOGS",
#             action="DELETE",
#             performed_by=auth_user_id,
#             record_id=log_id,
#             description=f"Audit log deleted (was: {existing.get('module')}/{existing.get('action')})",
#             old_values=existing,
#             request=request,
#         )

#         return success_response(message="Audit log deleted successfully.")

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception(e)
#         internal_server_error("Unable to delete audit log.")
import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, internal_server_error
from app.core.audit import record_audit_log

audit_log_repo = SupabaseRepository("audit_logs")

AUDIT_LOG_SELECT = "*, employees(full_name, employee_id, profile_photo, work_location)"


# ==========================================
# CHENNAI CHECK-IN / CHECK-OUT LOCATION MASKING (display only)
# ==========================================
# Chennai staff can check in/out from anywhere. The real GPS fix and
# resolved address are still stored untouched on the attendance row
# (check_in_latitude / check_in_address, ...) and in the raw audit row
# in the database -- nothing is lost. But in what the Audit Logs pages
# and the dashboards' Recent Activity panels *receive* from this API,
# those CHECK_IN / CHECK_OUT entries show one fixed label instead of
# wherever the person actually was, and the raw coordinates / address
# are stripped so they can't be read openly from the response either
# (the frontends only live-geocode when coordinates are present, so
# removing them also stops a re-geocode from revealing the real spot).
#
# A row is masked when the employee's Work Location says Chennai, OR the
# check-in/out spot itself is in Chennai (address / coordinates).
# Every other location's entries are returned exactly as before.
# The label shown instead of the real location:
_DISPLAY_LABEL = "CHN-RKM | NGB-AKR | PIN-600034"


def _get_display_label() -> str:
    return _DISPLAY_LABEL


_MASKED_ACTIONS = {"CHECK_IN": "check_in_address", "CHECK_OUT": "check_out_address"}

_LOCATION_KEYS = (
    "check_in_latitude",
    "check_in_longitude",
    "check_in_address",
    "check_out_latitude",
    "check_out_longitude",
    "check_out_address",
    "latitude",
    "longitude",
    "address",
)


# employees.work_location is free text ("Chennai Office", "Chennai - HQ",
# sometimes just the area name), so match on any of these fragments rather
# than only the literal word "chennai".
_CHENNAI_KEYWORDS = ("chennai", "madras", "nungambakkam", "nungabakkam", "rajkamal")

# The attendance audit message ends with "... — at <configured site name>"
# (see check_in/check_out in app/attendance/services.py). That site name is
# the *real* place the person checked in from, so it is dropped from the
# message of a masked row -- the masked label is shown as the location.
_AT_SITE_CLAUSE = re.compile(r"\s+[\u2014-]\s+at\s+.*$", re.IGNORECASE)


def _is_chennai_employee(record: dict) -> bool:
    employee = record.get("employees") or {}
    work_location = (employee.get("work_location") or "").lower()
    return any(keyword in work_location for keyword in _CHENNAI_KEYWORDS)


# Rough box around Greater Chennai, used when a row has coordinates but no
# readable address.
_CHENNAI_BBOX = (12.80, 13.30, 79.95, 80.40)  # lat_min, lat_max, lon_min, lon_max


def _unwrap(value):
    """audit `changes` values are {"old": ..., "new": ...} pairs."""
    if isinstance(value, dict) and "new" in value:
        return value["new"]
    return value


def _is_chennai_checkin_point(changes: dict) -> bool:
    """True when the stored check-in/out spot itself is in Chennai (its
    address mentions Chennai/Madras, or its coordinates fall inside the
    Chennai box) -- covers Chennai staff whose Work Location field was
    left blank or typed differently."""

    for key in ("check_in_address", "check_out_address", "address"):
        text = _unwrap(changes.get(key))
        if isinstance(text, str) and any(
            word in text.lower() for word in ("chennai", "madras")
        ):
            return True

    lat_min, lat_max, lon_min, lon_max = _CHENNAI_BBOX
    for lat_key, lon_key in (
        ("check_in_latitude", "check_in_longitude"),
        ("check_out_latitude", "check_out_longitude"),
        ("latitude", "longitude"),
    ):
        try:
            lat = float(_unwrap(changes.get(lat_key)))
            lon = float(_unwrap(changes.get(lon_key)))
        except (TypeError, ValueError):
            continue
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return True

    return False


def _mask_chennai_location(record: dict) -> dict:
    """Return `record` with its location replaced by the Chennai label
    when it is a Chennai ATTENDANCE check-in/out -- either the employee's
    Work Location says Chennai, or the check-in/out spot itself is in
    Chennai. Never raises -- on anything unexpected the record is
    returned as it was."""

    try:
        action = (record.get("action") or "").upper()
        address_key = _MASKED_ACTIONS.get(action)

        if not address_key or (record.get("module") or "").upper() != "ATTENDANCE":
            return record

        label = _get_display_label()

        if not label:
            return record

        raw = record.get("description")
        details = None

        if isinstance(raw, str):
            try:
                details = json.loads(raw)
            except ValueError:
                details = None
        elif isinstance(raw, dict):
            details = dict(raw)

        if not isinstance(details, dict):
            details = {"message": raw if isinstance(raw, str) else None}

        changes = dict(details.get("changes") or {})

        if not (_is_chennai_employee(record) or _is_chennai_checkin_point(changes)):
            return record

        message = details.get("message")
        if isinstance(message, str):
            details["message"] = _AT_SITE_CLAUSE.sub("", message).rstrip()

        for key in _LOCATION_KEYS:
            changes.pop(key, None)

        changes[address_key] = {"old": None, "new": label}
        details["changes"] = changes

        masked = dict(record)
        masked["description"] = json.dumps(details, default=str)
        return masked

    except Exception as e:
        logger.error(f"Chennai location masking failed: {e}")
        return record


def _mask_records(records):
    return [_mask_chennai_location(r) for r in (records or [])]


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
            data={
                "records": _mask_records(records),
                "total": total,
                "page": page,
                "limit": limit,
            },
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

        return success_response(
            message="Audit log fetched successfully.",
            data=_mask_chennai_location(record),
        )

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
            data={
                "records": _mask_records(records),
                "total": total,
                "page": page,
                "limit": limit,
            },
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
            data={
                "records": _mask_records(records),
                "total": total,
                "page": page,
                "limit": limit,
            },
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

        # `action` is usually a single value (CHECK_IN, CHECK_OUT, ...), but
        # callers that need an OR across a small family of actions — e.g.
        # the Audit Logs UI's "Site Visit" quick filter, which has to match
        # both SITE_VISIT_ARRIVE and SITE_VISIT_DEPART — pass a
        # comma-separated list instead. SupabaseRepository.list() only
        # supports .eq() filters, so a multi-value list falls through to a
        # raw .in_() query here rather than going through the repo.
        actions = [a.strip() for a in action.split(",") if a.strip()]

        if len(actions) > 1:
            from app.core.database import supabase_admin

            response = (
                supabase_admin.table("audit_logs")
                .select(AUDIT_LOG_SELECT, count="exact")
                .in_("action", actions)
                .order("created_at", desc=True)
                .range(start, end)
                .execute()
            )
            records, total = response.data or [], (response.count or 0)
        else:
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
            data={
                "records": _mask_records(records),
                "total": total,
                "page": page,
                "limit": limit,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch audit logs.")


# ==========================================
# DATE-RANGE FILTERED LOGS (Audit Logs calendar filter)
# ==========================================
#
# `start` / `end` are ISO datetimes (the frontend sends the user's local
# day converted to UTC, so "Oct 1" means Oct 1 in the viewer's timezone,
# not UTC). Can be combined with a module, or one/more actions (comma
# separated, same as get_action_logs). SupabaseRepository.list() only
# supports .eq() filters, so this goes straight to supabase_admin.


def get_logs_in_range(
    page: int = 1,
    limit: int = 50,
    module: Optional[str] = None,
    action: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    try:
        from app.core.database import supabase_admin

        size = max(min(limit, 200), 1)
        range_start = (max(page, 1) - 1) * size
        range_end = range_start + size - 1

        query = supabase_admin.table("audit_logs").select(
            AUDIT_LOG_SELECT, count="exact"
        )

        if module:
            query = query.eq("module", module)

        if action:
            actions = [a.strip() for a in action.split(",") if a.strip()]
            if len(actions) > 1:
                query = query.in_("action", actions)
            elif actions:
                query = query.eq("action", actions[0])

        if start:
            query = query.gte("created_at", start)
        if end:
            query = query.lt("created_at", end)

        response = (
            query.order("created_at", desc=True).range(range_start, range_end).execute()
        )

        return success_response(
            message="Audit logs fetched successfully.",
            data={
                "records": _mask_records(response.data or []),
                "total": response.count or 0,
                "page": page,
                "limit": limit,
            },
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
            message="Audit logs fetched successfully.",
            data=_mask_records(response.data),
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
