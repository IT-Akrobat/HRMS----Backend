# ---------------------------------------------------------------------
# Mappls (MapmyIndia) integration
# ---------------------------------------------------------------------
# Mappls is CE Info Systems' official India map/address service. It has
# far better street/locality-level detail for Indian addresses than
# OpenStreetMap/Nominatim does (Nominatim's India coverage is often only
# mapped down to locality/city level), but it's only ever called for
# coordinates that fall inside India (see is_in_india() and
# app/locations/routes.py) — mirrors the OneMap/Singapore setup in
# onemap_service.py, just with Mappls' own OAuth + endpoint shapes.
#
# Mappls needs an OAuth2 client-credentials token (client_id/secret ->
# access_token, valid ~24h). We fetch it once and cache it in memory,
# refreshing automatically when it's close to expiry, so normal
# requests never wait on a token call.

import time

import httpx

from app.core.config import MAPPLS_CLIENT_ID, MAPPLS_CLIENT_SECRET
from app.core.logger import logger

MAPPLS_TOKEN_URL = "https://outpost.mappls.com/api/security/oauth/token"
MAPPLS_REVGEOCODE_URL = "https://search.mappls.com/search/address/rev-geocode"

# India's bounding box (rough, generous padding — covers the mainland
# plus the Andaman & Nicobar and Lakshadweep islands). Mirrors
# IN_LAT_MIN/MAX in src/utils/Geocode.jsx on the frontend. Used to skip
# calling Mappls for any point that clearly isn't in India.
IN_LAT_MIN, IN_LAT_MAX = 6.5, 37.6
IN_LON_MIN, IN_LON_MAX = 68.0, 97.5

_token_cache = {"token": None, "expiry": 0}


def is_in_india(lat: float, lon: float) -> bool:
    return IN_LAT_MIN <= lat <= IN_LAT_MAX and IN_LON_MIN <= lon <= IN_LON_MAX


def _get_token() -> str | None:
    """Returns a cached Mappls access token, requesting a new one only
    once it's within an hour of expiry. Returns None (never raises) if
    Mappls credentials aren't configured or the token call fails, so
    callers can fall back to OpenStreetMap instead of erroring out.
    """

    if not MAPPLS_CLIENT_ID or not MAPPLS_CLIENT_SECRET:
        logger.warning(
            "Mappls token fetch skipped: MAPPLS_CLIENT_ID/MAPPLS_CLIENT_SECRET not set."
        )
        return None

    if _token_cache["token"] and time.time() < _token_cache["expiry"] - 3600:
        return _token_cache["token"]

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.post(
                MAPPLS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": MAPPLS_CLIENT_ID,
                    "client_secret": MAPPLS_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()

        token = payload.get("access_token")
        if not token:
            # A 200 with no access_token means Mappls accepted the
            # request but rejected the credentials -- log the payload so
            # that shows up in server logs instead of every check-in
            # silently falling back to Nominatim with no clue why.
            logger.warning(f"Mappls token endpoint returned no access_token: {payload}")
            return None

        expires_in = payload.get("expires_in")
        _token_cache["token"] = token
        # Fall back to "23 hours from now" if expires_in is ever
        # missing/malformed (Mappls tokens are typically ~24h).
        _token_cache["expiry"] = (
            time.time() + int(expires_in) if expires_in else time.time() + 23 * 3600
        )
        return token

    except Exception as e:
        logger.warning(f"Mappls token fetch failed: {e}")
        return None


def reverse_geocode_in(lat: float, lon: float) -> str | None:
    """Reverse-geocodes an India coordinate via Mappls and returns a
    formatted "House/Building, Street, Locality, City, State, Pincode"
    style string, or None on any failure (missing credentials, network
    error, no result) -- callers should fall back to OpenStreetMap in
    that case.
    """

    token = _get_token()
    if not token:
        logger.warning(
            "Mappls reverse geocode skipped: no token (missing/invalid "
            "MAPPLS_CLIENT_ID/MAPPLS_CLIENT_SECRET, or the token request is "
            "failing — check the 'Mappls token fetch failed' warning above)."
        )
        return None

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(
                MAPPLS_REVGEOCODE_URL,
                params={
                    "lat": lat,
                    "lng": lon,
                    "access_token": token,
                },
            )
            response.raise_for_status()
            payload = response.json()

        results = payload.get("results") or []
        if not results:
            logger.warning(
                f"Mappls reverse geocode returned no results for "
                f"({lat}, {lon}); raw response: {payload}"
            )
            return None

        info = results[0]

        # Drop Mappls' blank-string placeholders.
        def clean(v):
            return v.strip() if v and str(v).strip() else None

        house_number = clean(info.get("houseNumber"))
        house_name = clean(info.get("houseName"))
        street = clean(info.get("street"))
        sub_locality = clean(info.get("subLocality"))
        locality = clean(info.get("locality"))
        village = clean(info.get("village"))
        city = clean(info.get("city"))
        state = clean(info.get("state"))
        pincode = clean(info.get("pincode"))

        # House/building line: "12, Rajkamal Apartments" style.
        building = (
            f"{house_number}, {house_name}"
            if house_number and house_name
            else house_name or house_number
        )

        # city is absent whenever village is present (rural vs urban --
        # see Mappls' docs), so this naturally picks whichever applies.
        parts = [
            building,
            street,
            sub_locality,
            locality,
            village,
            city,
            state,
            pincode,
        ]
        parts = [p for p in parts if p]
        # Drop consecutive duplicates (e.g. locality === city for towns).
        parts = [p for i, p in enumerate(parts) if i == 0 or p != parts[i - 1]]

        if parts:
            return ", ".join(parts)

        # Mappls always includes a best-effort formatted_address even
        # when the structured fields above are mostly empty (e.g. a
        # point matched only to a distant POI) -- better than nothing.
        return clean(info.get("formatted_address"))

    except Exception as e:
        logger.warning(f"Mappls reverse geocode failed: {e}")
        return None
