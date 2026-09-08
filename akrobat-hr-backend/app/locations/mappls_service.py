# ---------------------------------------------------------------------
# Mappls (MapmyIndia) integration (NEW FILE)
# ---------------------------------------------------------------------
# Mappls is India's own digital mapping platform. It gives far better
# building/street/locality detail for Indian addresses than OpenStreetMap
# does — Nominatim's coverage of India is crowd-sourced and noticeably
# thinner outside a handful of well-mapped cities, which is why check-in
# locations were resolving well in Singapore (via OneMap) but poorly in
# India. This module is only ever called for coordinates that fall
# inside India (see is_in_india() and app/locations/routes.py) — same
# pattern as onemap_service.py, just with a plain static API key instead
# of a login/token flow.

import httpx

from app.core.config import MAPPLS_API_KEY
from app.core.logger import logger

MAPPLS_REVGEOCODE_URL = "https://apis.mappls.com/advancedmaps/v1/{key}/rev_geocode"

# India's bounding box (rough, generous padding). Covers the mainland
# plus the Andaman & Nicobar and Lakshadweep islands. Used to skip
# calling Mappls for any point that clearly isn't in India, the same way
# is_in_singapore() gates the OneMap call.
IN_LAT_MIN, IN_LAT_MAX = 6.5, 37.6
IN_LON_MIN, IN_LON_MAX = 68.0, 97.5


def is_in_india(lat: float, lon: float) -> bool:
    return IN_LAT_MIN <= lat <= IN_LAT_MAX and IN_LON_MIN <= lon <= IN_LON_MAX


def _clean(value):
    """Drops Mappls's blank/placeholder field values ("", "NA", "-")."""
    if not value:
        return None
    v = str(value).strip()
    return v if v and v.upper() not in ("NA", "N/A", "-", "NIL") else None


def reverse_geocode_india(lat: float, lon: float) -> str | None:
    """Reverse-geocodes an Indian coordinate via Mappls and returns a
    formatted "POI/Building, Street, Locality, City, State, Pincode"
    style string, or None on any failure (missing key, network error, no
    result) — callers should fall back to OpenStreetMap in that case.
    """

    if not MAPPLS_API_KEY:
        logger.warning("Mappls reverse geocode skipped: MAPPLS_API_KEY not set.")
        return None

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(
                MAPPLS_REVGEOCODE_URL.format(key=MAPPLS_API_KEY),
                params={"lat": lat, "lng": lon},
            )
            response.raise_for_status()
            payload = response.json()

        results = payload.get("results") or []
        if not results:
            # Mirrors the OneMap module's logging: a 200 with no results
            # can mean "genuinely no address here" or "key rejected/quota
            # exceeded" (Mappls sometimes returns 200 with an empty/error
            # body rather than a 4xx for bad keys) — log the raw payload
            # so it's distinguishable in server logs instead of silently
            # always falling back to Nominatim.
            logger.warning(
                f"Mappls reverse geocode returned no results for "
                f"({lat}, {lon}); raw response: {payload}"
            )
            return None

        info = results[0]

        # Prefer building the address ourselves from the structured
        # fields (matches the "Building, Area, City, State" shape used
        # everywhere else in the app — see formatAddress() in
        # utils/Geocode.jsx) — falling back to Mappls's own
        # formatted_address only if none of the structured fields came
        # back at all.
        poi = _clean(info.get("poi"))
        house = _clean(info.get("house_number"))
        street = _clean(info.get("street"))
        locality = (
            _clean(info.get("village_township_locality"))
            or _clean(info.get("subSubLocality"))
            or _clean(info.get("subLocality"))
        )
        city = _clean(info.get("city")) or _clean(info.get("district"))
        state = _clean(info.get("state"))
        pincode = _clean(info.get("pincode"))

        building = ", ".join(p for p in [poi or house, street] if p) or None

        parts = [building, locality, city, state, pincode]
        parts = [p for p in parts if p]
        # Drop consecutive duplicates (e.g. locality === city for
        # smaller towns) — same rule formatAddress() applies on the
        # frontend for Nominatim results.
        parts = [p for i, p in enumerate(parts) if i == 0 or p != parts[i - 1]]

        if parts:
            return ", ".join(parts)

        return _clean(info.get("formatted_address"))

    except Exception as e:
        logger.warning(f"Mappls reverse geocode failed: {e}")
        return None
