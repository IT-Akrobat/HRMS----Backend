from typing import Optional

from fastapi import HTTPException, Request

from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import internal_server_error, forbidden
from app.core.messages import DOCUMENT_UPLOADED, DOCUMENT_DELETED, UPDATED
from app.core.audit import record_audit_log
from app.core.rbac import has_permission
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

document_repo = SupabaseRepository("documents")

DOCUMENT_SELECT = "*, employees(employee_id, full_name)"


# ==========================================
# CREATE DOCUMENT (HR / Admin only — requires CREATE_DOCUMENT)
# ==========================================


def create_document(data, current_user=None, request: Optional[Request] = None):
    try:
        document_data = document_repo.create(
            {
                "employee_id": str(data.employee_id),
                "document_name": data.document_name,
                "document_type": data.document_type,
                "file_url": data.file_url,
                "expiry_date": data.expiry_date.isoformat() if data.expiry_date else None,
                "remarks": data.remarks,
            }
        )

        record_audit_log(
            module="DOCUMENTS",
            action="CREATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=document_data.get("employee_id"),
            record_id=document_data.get("id"),
            description=f"Document uploaded: {data.document_name} ({data.document_type})",
            new_values=document_data,
            request=request,
        )

        return success_response(message=DOCUMENT_UPLOADED, data=document_data)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to create document record.")


# ==========================================
# GET ALL DOCUMENTS (HR / Admin only — company-wide, requires VIEW_DOCUMENTS)
# ==========================================


def get_documents(page: int = 1, limit: int = 20):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 100), 1)
        end = start + max(min(limit, 100), 1) - 1

        records, total = document_repo.list(
            select=DOCUMENT_SELECT,
            order_by="created_at",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Documents fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch documents.")


# ==========================================
# GET MY DOCUMENTS (self-service — new endpoint, additive)
# ==========================================


def get_my_documents(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(message="Documents fetched successfully.", data=[])

        records, _total = document_repo.list(
            select=DOCUMENT_SELECT,
            filters={"employee_id": employee_id},
            order_by="created_at",
            ascending=False,
        )

        return success_response(message="Documents fetched successfully.", data=records)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch documents.")


# ==========================================
# GET ONE DOCUMENT (HR/Admin via VIEW_DOCUMENTS, or the owning employee)
# ==========================================


def get_document(document_id: str, auth_user_id: str):
    try:
        record = document_repo.get_by_id_or_404(
            document_id, "Document not found.", select=DOCUMENT_SELECT
        )

        if not has_permission(auth_user_id, "VIEW_DOCUMENTS"):
            own_employee_id = get_employee_id_for_auth_user(auth_user_id)

            if not own_employee_id or record.get("employee_id") != own_employee_id:
                forbidden("You don't have permission to view this document.")

        return success_response(message="Document fetched successfully.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch document.")


# ==========================================
# GET DOCUMENTS OF A SPECIFIC EMPLOYEE
# (HR/Admin via VIEW_DOCUMENTS, or that employee viewing their own)
# ==========================================


def get_employee_documents(employee_id: str, auth_user_id: str):
    try:
        if not has_permission(auth_user_id, "VIEW_DOCUMENTS"):
            own_employee_id = get_employee_id_for_auth_user(auth_user_id)

            if not own_employee_id or own_employee_id != employee_id:
                forbidden("You don't have permission to view this employee's documents.")

        records, _total = document_repo.list(
            select=DOCUMENT_SELECT,
            filters={"employee_id": employee_id},
            order_by="created_at",
            ascending=False,
        )

        return success_response(message="Documents fetched successfully.", data=records)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch employee documents.")


# ==========================================
# UPDATE DOCUMENT (HR / Admin only — requires EDIT_DOCUMENT)
# ==========================================


def update_document(
    document_id: str,
    data,
    current_user=None,
    request: Optional[Request] = None,
):
    try:
        existing = document_repo.get_by_id_or_404(document_id, "Document not found.")

        values = data.model_dump(exclude_unset=True)

        if "expiry_date" in values and values["expiry_date"] is not None:
            values["expiry_date"] = values["expiry_date"].isoformat()

        updated = document_repo.update(document_id, values)

        record_audit_log(
            module="DOCUMENTS",
            action="UPDATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=updated.get("employee_id"),
            record_id=document_id,
            description="Document record updated",
            old_values=existing,
            new_values=updated,
            request=request,
        )

        return success_response(message=UPDATED, data=updated)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update document.")


# ==========================================
# DELETE DOCUMENT (HR / Admin only — requires DELETE_DOCUMENT)
# ==========================================


def delete_document(document_id: str, current_user=None, request: Optional[Request] = None):
    try:
        existing = document_repo.get_by_id_or_404(document_id, "Document not found.")

        document_repo.delete(document_id)

        record_audit_log(
            module="DOCUMENTS",
            action="DELETE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=existing.get("employee_id"),
            record_id=document_id,
            description=f"Document deleted: {existing.get('document_name')}",
            old_values=existing,
            request=request,
        )

        return success_response(message=DOCUMENT_DELETED)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to delete document.")
