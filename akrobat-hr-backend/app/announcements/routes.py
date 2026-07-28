from fastapi import APIRouter, Depends

from app.announcements.schemas import (
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)

from app.announcements.services import (
    create_announcement,
    get_announcements,
    get_active_announcements,
    get_announcement,
    update_announcement,
    delete_announcement,
)

from app.core.security import get_current_user
from app.core.helpers.employee_helper import get_employee_id_for_auth_user
from app.core.exceptions import not_found

router = APIRouter(prefix="/announcements", tags=["Announcements"])


# =========================
# CREATE ANNOUNCEMENT
# =========================


@router.post("/")
def create(data: CreateAnnouncementRequest, user=Depends(get_current_user)):

    # user.id from get_current_user is the Supabase AUTH user id, but
    # announcements.created_by has a foreign key to employees(id) — passing
    # the auth id straight through violates that FK (23503). Resolve it to
    # the linked employee first, same as other self-service endpoints do.
    employee_id = get_employee_id_for_auth_user(user.id)

    if not employee_id:
        not_found("No employee profile linked to this account.")

    return create_announcement(data, employee_id)


# =========================
# GET ALL ANNOUNCEMENTS
# =========================


@router.get("/")
def all_announcements(user=Depends(get_current_user)):

    return get_announcements()


# =========================
# GET ACTIVE ANNOUNCEMENTS
# =========================


@router.get("/active")
def active_announcements(user=Depends(get_current_user)):

    return get_active_announcements()


# =========================
# GET SINGLE ANNOUNCEMENT
# =========================


@router.get("/{announcement_id}")
def get_one(announcement_id: str, user=Depends(get_current_user)):

    return get_announcement(announcement_id)


# =========================
# UPDATE ANNOUNCEMENT
# =========================


@router.put("/{announcement_id}")
def update(
    announcement_id: str,
    data: UpdateAnnouncementRequest,
    user=Depends(get_current_user),
):

    return update_announcement(announcement_id, data.model_dump(exclude_unset=True))


# =========================
# DELETE ANNOUNCEMENT
# =========================


@router.delete("/{announcement_id}")
def delete(announcement_id: str, user=Depends(get_current_user)):

    return delete_announcement(announcement_id)
