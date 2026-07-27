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

router = APIRouter(prefix="/announcements", tags=["Announcements"])


# =========================
# CREATE ANNOUNCEMENT
# =========================


@router.post("/")
def create(data: CreateAnnouncementRequest, user=Depends(get_current_user)):

    return create_announcement(data, user.id)


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
