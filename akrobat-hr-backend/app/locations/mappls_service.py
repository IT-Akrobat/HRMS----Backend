# ---------------------------------------------------------------------
# Mappls (MapmyIndia) integration
# ---------------------------------------------------------------------
# Mappls is CE Info Systems' official India map/address service. It has
# far better street/locality-level detail for Indian addresses than
# OpenStreetMap/Nominatim does (Nominatim's India coverage is often only
# mapped down to locality/city level), but it's only ever called for
# coordinates that fall inside India (see is_in_india() and
# app/locations/routes.py) — mirrors the OneMap/Singapore setup in
# onemap_service.py.
#
# Mappls supports two different credential styles depending on the
# "application" type created in their console
# (auth.mappls.com/console/#/home/dashboard/applications):
#
#   - "Cloud App" issues a single STATIC KEY (a long token, no
#     client_id/secret pair). It's embedded directly in the URL path --
#     no separate token-exchange call needed at all. This is what
#     MAPPLS_REST_KEY below is for, and is the simpler/recommended path
#     for a headless backend like this one.
#   - "Web App" (and some other types) instead issue an OAuth2
#     client_id/client_secret pair, exchanged for a short-lived
#     access_token via a POST to MAPPLS_TOKEN_URL. MAPPLS_CLIENT_ID/
#     MAPPLS_CLIENT_SECRET below are for that path.
#
# Both are supported here -- reverse_geocode_in() tries the static key
# first (if set), then OAuth (if those are set instead), then gives up.
# Whichever one you actually generated in the console, just set the
# matching env var(s) and this picks the right method automatically.

import time

import httpx

from app.core.config import (
    MAPPLS_CLIENT_ID,
    MAPPLS_CLIENT_SECRET,
    MAPPLS_REST_KEY,
)
from app.core.logger import logger

MAPPLS_TOKEN_URL = "https://outpost.mappls.com/api/security/oauth/token"
MAPPLS_REVGEOCODE_URL_OAUTH = "https://search.mappls.com/search/address/rev-geocode"
# Static-key style: the key sits in the URL path itself, not as a query
# param or bearer token -- same pattern Mappls uses for their map-tile
# SDK URLs (.../advancedmaps/api/<key>/map_sdk).
MAPPLS_REVGEOCODE_URL_STATIC = (
    "https://apis.mappls.com/advancedmaps/v1/{key}/rev_geocode"
)

# India's bounding box (rough, generous padding — covers the mainland
# plus the Andaman & Nicobar and Lakshadweep islands). Mirrors
# IN_LAT_MIN/MAX in src/utils/Geocode.jsx on the frontend. Used to skip
# calling Mappls for any point that clearly isn't in India.
IN_LAT_MIN, IN_LAT_MAX = 6.5, 37.6
IN_LON_MIN, IN_LON_MAX = 68.0, 97.5

_token_cache = {"token": None, "expiry": 0}


def is_in_india(lat: float, lon: float) -> bool:
    return IN_LAT_MIN <= lat <= IN_LAT_MAX and IN_LON_MIN <= lon <= IN_LON_MAX


def _get_oauth_token() -> str | None:
    """Returns a cached Mappls OAuth access token, requesting a new one
    only once it's within an hour of expiry. Returns None (never raises)
    if the OAuth credentials aren't configured or the token call fails.
    Only relevant if you generated a client_id/client_secret pair
    (e.g. from a "Web App" application) rather than a static key.
    """

    if not MAPPLS_CLIENT_ID or not MAPPLS_CLIENT_SECRET:
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
        logger.warning(f"Mappls OAuth token fetch failed: {e}")
        return None


def _parse_mappls_result(payload: dict, lat: float, lon: float) -> str | None:
    """Shared response parsing for both auth styles -- Mappls returns
    the same result shape regardless of which endpoint/credential type
    was used to reach it.
    """

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


def _reverse_geocode_static_key(lat: float, lon: float) -> str | None:
    """Reverse-geocodes via a static key ("Cloud App" credential type) --
    no token exchange, the key is embedded directly in the URL path.
    """

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(
                MAPPLS_REVGEOCODE_URL_STATIC.format(key=MAPPLS_REST_KEY),
                params={"lat": lat, "lng": lon},
            )
            response.raise_for_status()
            payload = response.json()

        return _parse_mappls_result(payload, lat, lon)

    except Exception as e:
        logger.warning(f"Mappls reverse geocode (static key) failed: {e}")
        return None


def _reverse_geocode_oauth(lat: float, lon: float) -> str | None:
    """Reverse-geocodes via an OAuth access_token ("Web App"/similar
    credential type -- client_id + client_secret exchanged for a token).
    """

    token = _get_oauth_token()
    if not token:
        return None

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(
                MAPPLS_REVGEOCODE_URL_OAUTH,
                params={"lat": lat, "lng": lon, "access_token": token},
            )
            response.raise_for_status()
            payload = response.json()

        return _parse_mappls_result(payload, lat, lon)

    except Exception as e:
        logger.warning(f"Mappls reverse geocode (OAuth) failed: {e}")
        return None


def reverse_geocode_in(lat: float, lon: float) -> str | None:
    """Reverse-geocodes an India coordinate via Mappls and returns a
    formatted "House/Building, Street, Locality, City, State, Pincode"
    style string, or None on any failure (missing credentials, network
    error, no result) -- callers should fall back to OpenStreetMap in
    that case.

    Tries the static-key method first (MAPPLS_REST_KEY -- simpler, no
    token exchange), then OAuth (MAPPLS_CLIENT_ID/SECRET) if that's what
    you configured instead. If neither is set, skips Mappls entirely.
    """

    if MAPPLS_REST_KEY:
        return _reverse_geocode_static_key(lat, lon)

    if MAPPLS_CLIENT_ID and MAPPLS_CLIENT_SECRET:
        return _reverse_geocode_oauth(lat, lon)

    logger.warning(
        "Mappls reverse geocode skipped: neither MAPPLS_REST_KEY nor "
        "MAPPLS_CLIENT_ID/MAPPLS_CLIENT_SECRET are set."
    )
    return None
