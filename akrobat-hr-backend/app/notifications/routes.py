from fastapi import APIRouter, Depends

from app.notifications.services import (
    get_my_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    delete_notification,
    get_celebrations_status,
)

from app.core.security import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# =========================
# LIST MY NOTIFICATIONS
# =========================


@router.get("/my")
def my_notifications(user=Depends(get_current_user)):

    return get_my_notifications(user.id)


# =========================
# CHECK FOR CELEBRATIONS
# =========================
# Polled by the frontend (e.g. alongside the existing /notifications/my
# poll in Header.jsx) to surface today's birthdays/work anniversaries as
# a real notification, gated by the requesting employee's own
# "Birthdays & work anniversaries" toggle.


@router.get("/celebrations-check")
def celebrations_check(user=Depends(get_current_user)):

    return get_celebrations_status(user.id)


# =========================
# MARK ALL AS READ
# =========================
# Registered before /{notification_id}/read so "my" isn't swallowed by the
# path parameter.


@router.put("/my/read-all")
def read_all_notifications(user=Depends(get_current_user)):

    return mark_all_notifications_read(user.id)


# =========================
# MARK ONE AS READ
# =========================


@router.put("/{notification_id}/read")
def read_notification(notification_id: str, user=Depends(get_current_user)):

    return mark_notification_read(user.id, notification_id)


# =========================
# DELETE ONE
# =========================


@router.delete("/{notification_id}")
def remove_notification(notification_id: str, user=Depends(get_current_user)):

    return delete_notification(user.id, notification_id)
