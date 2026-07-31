from fastapi import APIRouter, Depends

from app.locations.schemas import CreateLocationRequest

from app.locations.services import (
    create_location,
    get_locations,
    get_location,
    update_location,
    delete_location,
)

# NEW: OneMap Singapore reverse-geocode helper (see app/locations/onemap_service.py)
from app.locations.onemap_service import is_in_singapore, reverse_geocode_sg

from app.core.security import get_current_user
from app.core.responses import success_response

router = APIRouter(prefix="/locations", tags=["Locations"])


@router.post("/")
def create(data: CreateLocationRequest, user=Depends(get_current_user)):

    return create_location(data)


@router.get("/")
def all_locations(user=Depends(get_current_user)):

    return get_locations()


# NEW: reverse-geocode proxy. Kept ahead of "/{location_id}" so the path
# doesn't get swallowed by that route.
#
# - Coordinate inside Singapore  -> calls OneMap, returns the exact
#   building/block/street address.
# - Coordinate outside Singapore -> returns in_singapore: false and no
#   address; the frontend (see src/utils/Geocode.jsx) then falls back
#   to its existing OpenStreetMap/Nominatim lookup, unchanged.
# - Coordinate inside Singapore but OneMap has no result / is
#   unreachable -> same fallback signal, so the frontend still tries
#   Nominatim rather than showing nothing.
@router.get("/reverse-geocode")
def reverse_geocode(lat: float, lon: float, user=Depends(get_current_user)):

    if not is_in_singapore(lat, lon):
        return success_response(
            "Coordinate is outside Singapore",
            {"in_singapore": False, "address": None},
        )

    address = reverse_geocode_sg(lat, lon)

    return success_response(
        "Reverse geocode complete",
        {"in_singapore": True, "address": address},
    )


@router.get("/{location_id}")
def one_location(location_id: str, user=Depends(get_current_user)):

    return get_location(location_id)


@router.put("/{location_id}")
def update(location_id: str, data: dict, user=Depends(get_current_user)):

    return update_location(location_id, data)


@router.delete("/{location_id}")
def delete(location_id: str, user=Depends(get_current_user)):

    return delete_location(location_id)
