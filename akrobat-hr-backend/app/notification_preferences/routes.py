from fastapi import APIRouter, Depends

from app.notification_preferences.schemas import UpdateNotificationPreferencesRequest

from app.notification_preferences.services import (
    get_my_preferences,
    update_my_preferences,
)

from app.core.security import get_current_user

router = APIRouter(
    prefix="/notification-preferences", tags=["Notification Preferences"]
)


# =========================
# GET MY PREFERENCES
# =========================


@router.get("/me")
def my_preferences(user=Depends(get_current_user)):

    return get_my_preferences(user.id)


# =========================
# UPDATE MY PREFERENCES
# =========================


@router.put("/me")
def update_preferences(
    data: UpdateNotificationPreferencesRequest, user=Depends(get_current_user)
):

    return update_my_preferences(user.id, data.model_dump(exclude_unset=True))
