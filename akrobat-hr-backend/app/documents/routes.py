from fastapi import APIRouter, Depends, Query, Request

from app.documents.schemas import CreateDocumentRequest, UpdateDocumentRequest

from app.documents.services import (
    create_document,
    get_documents,
    get_my_documents,
    get_document,
    get_employee_documents,
    update_document,
    delete_document,
)

from app.core.security import get_current_user
from app.core.rbac import require_permission

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
# GET MY DOCUMENTS (self-service — any authenticated employee, own records only)
# ==========================================


@router.get("/my")
def get_my(user=Depends(get_current_user)):
    return get_my_documents(user.id)


# ==========================================
# GET DOCUMENTS OF A SPECIFIC EMPLOYEE (HR/Admin, or that employee themself)
# ==========================================


@router.get("/employee/{employee_id}")
def get_employee(employee_id: str, user=Depends(get_current_user)):
    return get_employee_documents(employee_id, auth_user_id=user.id)


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
