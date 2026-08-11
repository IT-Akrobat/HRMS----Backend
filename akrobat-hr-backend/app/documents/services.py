import io
import uuid
import zipfile
from typing import Optional

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import SUPABASE_DOCUMENTS_BUCKET
from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, internal_server_error, forbidden, not_found
from app.core.messages import DOCUMENT_UPLOADED, DOCUMENT_DELETED, UPDATED
from app.core.audit import record_audit_log
from app.core.rbac import has_permission
from app.core.database import supabase_admin
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

document_repo = SupabaseRepository("documents")

DOCUMENT_SELECT = "*, employees(employee_id, full_name)"

# ==========================================
# SELF-SERVICE UPLOAD — allowed file types
# ==========================================
# Employee / Manager / HR Admin / Super Admin (any authenticated user,
# uploading their OWN document from My Profile > Documents Summary's "+"
# button). Keep this in sync with ACCEPTED_DOCUMENT_TYPES on the frontend
# (src/services/documentsService.js).
ALLOWED_DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


def _extension(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _validate_and_read_file(file: UploadFile) -> tuple[bytes, str, str]:
    """Validates extension + size, returns (bytes, extension, content_type)."""

    ext = _extension(file.filename or "")

    if ext not in ALLOWED_DOCUMENT_TYPES:
        bad_request(
            "Unsupported file type. Please upload a PDF, Word, Excel, or JPG/PNG file."
        )

    content = file.file.read()

    if not content:
        bad_request("The selected file is empty.")

    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        bad_request("File is too large. Maximum allowed size is 10MB.")

    return content, ext, ALLOWED_DOCUMENT_TYPES[ext]


def _upload_to_storage(
    employee_id: str, content: bytes, ext: str, content_type: str
) -> str:
    """Uploads file bytes to the private Supabase Storage bucket and
    returns the storage object path — this is what gets saved in
    documents.file_url (a path, not a public URL, since the bucket is
    private and files are only ever served back out through our own
    authenticated download endpoints)."""

    storage_path = f"{employee_id}/{uuid.uuid4().hex}{ext}"

    try:
        supabase_admin.storage.from_(SUPABASE_DOCUMENTS_BUCKET).upload(
            storage_path,
            content,
            {"content-type": content_type},
        )
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to upload the file. Please try again.")

    return storage_path


def _download_bytes_from_storage(storage_path: str) -> bytes:
    try:
        return supabase_admin.storage.from_(SUPABASE_DOCUMENTS_BUCKET).download(
            storage_path
        )
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to retrieve the file from storage.")


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
                "expiry_date": (
                    data.expiry_date.isoformat() if data.expiry_date else None
                ),
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
# SELF-SERVICE UPLOAD (Employee / Manager / HR Admin / Super Admin — any
# authenticated user, uploads an actual file against their OWN employee
# record only; no CREATE_DOCUMENT permission required, same "own record
# only" convention as get_my_documents below)
# ==========================================


def upload_my_document(
    file: UploadFile,
    document_name: str,
    document_type: str,
    expiry_date=None,
    remarks: Optional[str] = None,
    current_user=None,
    request: Optional[Request] = None,
):
    try:
        employee_id = get_employee_id_for_auth_user(current_user.id)

        if not employee_id:
            forbidden("No employee record is linked to this account.")

        if not document_name or not document_name.strip():
            bad_request("Document name is required.")

        if not document_type or not document_type.strip():
            bad_request("Document type is required.")

        content, ext, content_type = _validate_and_read_file(file)
        storage_path = _upload_to_storage(employee_id, content, ext, content_type)

        document_data = document_repo.create(
            {
                "employee_id": employee_id,
                "document_name": document_name.strip(),
                "document_type": document_type.strip(),
                "file_url": storage_path,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
                "remarks": remarks,
            }
        )

        record_audit_log(
            module="DOCUMENTS",
            action="CREATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=employee_id,
            record_id=document_data.get("id"),
            description=f"Document self-uploaded: {document_name} ({ext})",
            new_values=document_data,
            request=request,
        )

        return success_response(message=DOCUMENT_UPLOADED, data=document_data)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to upload document.")


# ==========================================
# DOWNLOAD ONE DOCUMENT'S FILE
# (the owning employee, or HR/Admin via VIEW_DOCUMENTS — same ownership
# rule as get_document below, but streams the actual file bytes instead
# of just the database record)
# ==========================================


def get_document_file(document_id: str, auth_user_id: str):
    try:
        record = document_repo.get_by_id_or_404(document_id, "Document not found.")

        if not has_permission(auth_user_id, "VIEW_DOCUMENTS"):
            own_employee_id = get_employee_id_for_auth_user(auth_user_id)

            if not own_employee_id or record.get("employee_id") != own_employee_id:
                forbidden("You don't have permission to view this document.")

        storage_path = record.get("file_url")

        if not storage_path:
            not_found("File not found for this document.")

        content = _download_bytes_from_storage(storage_path)
        ext = _extension(storage_path)
        content_type = ALLOWED_DOCUMENT_TYPES.get(ext, "application/octet-stream")
        filename = f"{record.get('document_name') or 'document'}{ext}"

        return StreamingResponse(
            io.BytesIO(content),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to download document.")


# ==========================================
# DOWNLOAD ALL DOCUMENTS (SUPER ADMIN ONLY — enforced at the route level
# via require_role([ADMIN]); this function assumes that check already
# passed) — zips every employee's uploaded document into one file.
# ==========================================


def download_all_documents_zip():
    try:
        records, _total = document_repo.list(
            select=DOCUMENT_SELECT, order_by="created_at", ascending=False
        )

        if not records:
            not_found("No documents have been uploaded yet.")

        buffer = io.BytesIO()
        used_names: set[str] = set()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for record in records:
                storage_path = record.get("file_url")

                if not storage_path:
                    continue

                try:
                    content = supabase_admin.storage.from_(
                        SUPABASE_DOCUMENTS_BUCKET
                    ).download(storage_path)
                except Exception as e:
                    # Skip a single missing/corrupt file rather than
                    # failing the whole archive for every other employee.
                    logger.exception(e)
                    continue

                employee = record.get("employees") or {}
                emp_code = employee.get("employee_id") or "UNKNOWN"
                emp_name = (employee.get("full_name") or "employee").replace(" ", "_")
                doc_name = (record.get("document_name") or "document").replace(" ", "_")
                ext = _extension(storage_path)

                arcname = f"{emp_code}_{emp_name}/{doc_name}{ext}"
                base_arcname = arcname
                counter = 1
                while arcname in used_names:
                    arcname = f"{base_arcname[: -len(ext)] if ext else base_arcname}_{counter}{ext}"
                    counter += 1
                used_names.add(arcname)

                zf.writestr(arcname, content)

        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="all-employee-documents.zip"'
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to build the documents archive.")


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
                forbidden(
                    "You don't have permission to view this employee's documents."
                )

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


def delete_my_document(
    document_id: str, current_user=None, request: Optional[Request] = None
):
    # Self-service delete — Employee / Manager / HR Admin / Super Admin,
    # always restricted to the CALLER'S OWN uploaded document. This backs
    # the trash-can icon next to each file on My Profile > Documents
    # Summary (the "+" button's counterpart) and deliberately does NOT
    # require DELETE_DOCUMENT the way DELETE /{document_id} below does —
    # that permission is HR ADMIN-only and covers deleting *anyone's*
    # document, which is a different, broader action than a user removing
    # their own upload.
    try:
        own_employee_id = get_employee_id_for_auth_user(current_user.id)

        if not own_employee_id:
            forbidden("No employee record is linked to this account.")

        existing = document_repo.get_by_id_or_404(document_id, "Document not found.")

        if existing.get("employee_id") != own_employee_id:
            forbidden("You can only delete your own documents.")

        document_repo.delete(document_id)

        record_audit_log(
            module="DOCUMENTS",
            action="DELETE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=existing.get("employee_id"),
            record_id=document_id,
            description=f"Document deleted (self-service): {existing.get('document_name')}",
            old_values=existing,
            request=request,
        )

        return success_response(message=DOCUMENT_DELETED)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to delete document.")


def delete_document(
    document_id: str, current_user=None, request: Optional[Request] = None
):
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
