from fastapi import APIRouter, Depends

from app.settings.schemas import SettingsRequest, UpdateSettingsRequest

from app.settings.services import (
    create_settings,
    get_settings,
    update_settings,
    delete_settings,
)

from app.core.security import get_current_user

router = APIRouter(prefix="/settings", tags=["Settings"])


# =========================
# CREATE SETTINGS
# =========================


@router.post("/")
def create(data: SettingsRequest, user=Depends(get_current_user)):

    return create_settings(data)


# =========================
# GET SETTINGS
# =========================


@router.get("/")
def settings(user=Depends(get_current_user)):

    return get_settings()


# =========================
# UPDATE SETTINGS
# =========================


@router.put("/")
def update(data: UpdateSettingsRequest, user=Depends(get_current_user)):

    return update_settings(data.model_dump(exclude_unset=True))


# =========================
# DELETE SETTINGS
# =========================


@router.delete("/")
def delete(user=Depends(get_current_user)):

    return delete_settings()
