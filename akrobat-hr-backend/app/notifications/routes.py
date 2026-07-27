from fastapi import APIRouter, Depends

from app.notifications.schemas import (
    CreateNotificationRequest,
    UpdateNotificationRequest,
)

from app.notifications.services import (
    create_notification,
    get_notifications,
    get_employee_notifications,
    get_notification,
    update_notification,
    mark_as_read,
    mark_all_as_read,
    delete_notification,
    broadcast_notification,
)

from app.core.security import get_current_user
from app.core.helpers.employee_helper import get_employee_id_for_auth_user
from app.core.exceptions import forbidden

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# =========================
# CREATE NOTIFICATION
# =========================


@router.post("/")
def create(data: CreateNotificationRequest, user=Depends(get_current_user)):

    return create_notification(data)


# =========================
# BROADCAST TO ALL EMPLOYEES
# =========================


@router.post("/broadcast")
def broadcast(data: CreateNotificationRequest, user=Depends(get_current_user)):

    return broadcast_notification(data)


# =========================
# GET ALL NOTIFICATIONS
# =========================


@router.get("/")
def all_notifications(user=Depends(get_current_user)):

    return get_notifications()


# =========================
# MY NOTIFICATIONS
# =========================
# `user.id` from get_current_user is the Supabase auth user id, not the
# employee_id the notifications table is keyed on (see notify_employee() /
# _serialize() in services.py) — this was previously passed straight
# through, so a logged-in employee's own notifications never matched.


@router.get("/my")
def my_notifications(user=Depends(get_current_user)):

    employee_id = get_employee_id_for_auth_user(user.id)

    if not employee_id:
        return get_employee_notifications("00000000-0000-0000-0000-000000000000")

    return get_employee_notifications(employee_id)


# =========================
# MARK ALL AS READ (for the caller)
# =========================


@router.put("/my/read-all")
def read_all(user=Depends(get_current_user)):

    employee_id = get_employee_id_for_auth_user(user.id)

    if not employee_id:
        forbidden("No employee profile is linked to this account.")

    return mark_all_as_read(employee_id)


# =========================
# GET SINGLE NOTIFICATION
# =========================


@router.get("/{notification_id}")
def get_one(notification_id: str, user=Depends(get_current_user)):

    return get_notification(notification_id)


# =========================
# UPDATE NOTIFICATION
# =========================


@router.put("/{notification_id}")
def update(
    notification_id: str,
    data: UpdateNotificationRequest,
    user=Depends(get_current_user),
):

    return update_notification(notification_id, data.model_dump(exclude_unset=True))


# =========================
# MARK AS READ
# =========================


@router.put("/{notification_id}/read")
def read(notification_id: str, user=Depends(get_current_user)):

    return mark_as_read(notification_id)


# =========================
# DELETE NOTIFICATION
# =========================


@router.delete("/{notification_id}")
def delete(notification_id: str, user=Depends(get_current_user)):

    return delete_notification(notification_id)
