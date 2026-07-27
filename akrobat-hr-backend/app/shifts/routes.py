from fastapi import APIRouter, Depends

from app.shifts.schemas import CreateShiftRequest

from app.shifts.services import (
    create_shift,
    get_shifts,
    get_shift_by_id,
    update_shift,
    delete_shift,
)

from app.core.security import get_current_user

router = APIRouter(prefix="/shifts", tags=["Shifts"])


# CREATE SHIFT


@router.post("/")
def create(data: CreateShiftRequest, user=Depends(get_current_user)):

    return create_shift(data)


# GET ALL SHIFTS


@router.get("/")
def all_shifts(user=Depends(get_current_user)):

    return get_shifts()


# GET SINGLE SHIFT


@router.get("/{shift_id}")
def get_one(shift_id: str, user=Depends(get_current_user)):

    return get_shift_by_id(shift_id)


# UPDATE SHIFT


@router.put("/{shift_id}")
def update(shift_id: str, data: dict, user=Depends(get_current_user)):

    return update_shift(shift_id, data)


# DELETE SHIFT


@router.delete("/{shift_id}")
def delete(shift_id: str, user=Depends(get_current_user)):

    return delete_shift(shift_id)
