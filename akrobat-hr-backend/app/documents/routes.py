from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.documents.schemas import CreateDocumentRequest, UpdateDocumentRequest

from app.documents.services import (
    create_document,
    get_documents,
    get_my_documents,
    get_document,
    get_document_file,
    get_employee_documents,
    update_document,
    delete_document,
    delete_my_document,
    upload_my_document,
    download_all_documents_zip,
)

from app.core.constants import ADMIN
from app.core.security import get_current_user
from app.core.rbac import require_permission
from app.core.permissions import require_role

router = APIRouter(prefix="/documents", tags=["Documents"])


# ==========================================
# CREATE DOCUMENT (HR / Admin only)
# ==========================================


@router.post("/")
def create(
    data: CreateDocumentRequest,
    request: Request,
    user=Depends(require_permission("CREATE_DOCUMENT")),
):
    return create_document(data, current_user=user, request=request)


# ==========================================
# GET ALL DOCUMENTS (HR / Admin only — company-wide view)
# ==========================================


@router.get("/")
def get_all(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user=Depends(require_permission("VIEW_DOCUMENTS")),
):
    return get_documents(page=page, limit=limit)


# ==========================================
# SELF-SERVICE UPLOAD (Employee / Manager / HR Admin — any authenticated
# user EXCEPT Super Admin; always uploads against the CALLER'S OWN
# employee record. This is the "+" button on My Profile > Documents
# Summary — not a way to add documents for someone else, and it does
# NOT require CREATE_DOCUMENT the way POST / above does. Super Admin is
# rejected server-side in upload_my_document() even if called directly;
# the button is also hidden for them in MyProfile.jsx.)
# ==========================================


@router.post("/my")
def upload_my(
    request: Request,
    file: UploadFile = File(...),
    document_name: str = Form(...),
    document_type: str = Form(...),
    expiry_date: Optional[date] = Form(None),
    remarks: Optional[str] = Form(None),
    user=Depends(get_current_user),
):
    return upload_my_document(
        file=file,
        document_name=document_name,
        document_type=document_type,
        expiry_date=expiry_date,
        remarks=remarks,
        current_user=user,
        request=request,
    )


# ==========================================
# GET MY DOCUMENTS (self-service — any authenticated employee, own records only)
# ==========================================


@router.get("/my")
def get_my(user=Depends(get_current_user)):
    return get_my_documents(user.id)


# ==========================================
# SELF-SERVICE DELETE (Employee / Manager / HR Admin / Super Admin —
# any authenticated user; restricted server-side to the CALLER'S OWN
# document. This is the trash-can icon on My Profile > Documents Summary
# — not a way to delete someone else's document, and it does NOT require
# DELETE_DOCUMENT the way DELETE /{document_id} below does.)
# ==========================================


@router.delete("/my/{document_id}")
def delete_my(
    document_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    return delete_my_document(document_id, current_user=user, request=request)


# ==========================================
# DOWNLOAD ALL DOCUMENTS — SUPER ADMIN ONLY
# ==========================================
# Zips every employee's uploaded document into one file. Deliberately
# gated with require_role([ADMIN]) rather than a permission (VIEW_DOCUMENTS
# already covers HR viewing individual records — this is intentionally a
# narrower, Super-Admin-exclusive bulk export, not something HR also gets).
#
# NOTE: this must stay registered BEFORE GET /{document_id} below —
# otherwise FastAPI would match "download-all" as a document_id and this
# route would never be reached.


@router.get("/download-all")
def download_all(user=Depends(require_role([ADMIN]))):
    return download_all_documents_zip()


# ==========================================
# GET DOCUMENTS OF A SPECIFIC EMPLOYEE (HR/Admin, or that employee themself)
# ==========================================


@router.get("/employee/{employee_id}")
def get_employee(employee_id: str, user=Depends(get_current_user)):
    return get_employee_documents(employee_id, auth_user_id=user.id)


# ==========================================
# DOWNLOAD ONE DOCUMENT'S FILE (HR/Admin via VIEW_DOCUMENTS, or the
# owning employee) — streams the actual file, not just the JSON record.
# ==========================================


@router.get("/{document_id}/file")
def download_one(document_id: str, user=Depends(get_current_user)):
    return get_document_file(document_id, auth_user_id=user.id)


# ==========================================
# GET ONE DOCUMENT (HR/Admin, or the owning employee)
# ==========================================


@router.get("/{document_id}")
def get_one(document_id: str, user=Depends(get_current_user)):
    return get_document(document_id, auth_user_id=user.id)


# ==========================================
# UPDATE DOCUMENT (HR / Admin only)
# ==========================================


@router.put("/{document_id}")
def update(
    document_id: str,
    data: UpdateDocumentRequest,
    request: Request,
    user=Depends(require_permission("EDIT_DOCUMENT")),
):
    return update_document(document_id, data, current_user=user, request=request)


# ==========================================
# DELETE DOCUMENT (HR / Admin only)
# ==========================================


@router.delete("/{document_id}")
def delete(
    document_id: str,
    request: Request,
    user=Depends(require_permission("DELETE_DOCUMENT")),
):
    return delete_document(document_id, current_user=user, request=request)
