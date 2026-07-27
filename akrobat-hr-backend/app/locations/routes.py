from fastapi import APIRouter, Depends

from app.locations.schemas import CreateLocationRequest

from app.locations.services import (
    create_location,
    get_locations,
    get_location,
    update_location,
    delete_location,
)

from app.core.security import get_current_user

router = APIRouter(prefix="/locations", tags=["Locations"])


@router.post("/")
def create(data: CreateLocationRequest, user=Depends(get_current_user)):

    return create_location(data)


@router.get("/")
def all_locations(user=Depends(get_current_user)):

    return get_locations()


@router.get("/{location_id}")
def one_location(location_id: str, user=Depends(get_current_user)):

    return get_location(location_id)


@router.put("/{location_id}")
def update(location_id: str, data: dict, user=Depends(get_current_user)):

    return update_location(location_id, data)


@router.delete("/{location_id}")
def delete(location_id: str, user=Depends(get_current_user)):

    return delete_location(location_id)
