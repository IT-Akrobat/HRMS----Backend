# ---------------------------------------------------------------------
# OneMap Singapore integration (NEW FILE)
# ---------------------------------------------------------------------
# OneMap is Singapore Land Authority's official address/map service.
# It gives far better building-name/block-number detail for Singapore
# addresses than OpenStreetMap does, but it ONLY covers Singapore — so
# this module is only ever called for coordinates that fall inside
# Singapore (see is_in_singapore() and app/locations/routes.py).
#
# OneMap needs a login token (email/password -> token, valid ~3 days).
# We fetch it once and cache it in memory, refreshing automatically
# when it's close to expiry, so normal requests never wait on a login
# call.

import time

import httpx

from app.core.config import ONEMAP_EMAIL, ONEMAP_PASSWORD
from app.core.logger import logger

ONEMAP_LOGIN_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"
ONEMAP_REVGEOCODE_URL = "https://www.onemap.gov.sg/api/public/revgeocode"

# Singapore's bounding box (rough, with a little padding). Used to skip
# calling OneMap for any point that clearly isn't in Singapore.
SG_LAT_MIN, SG_LAT_MAX = 1.15, 1.48
SG_LON_MIN, SG_LON_MAX = 103.59, 104.05

_token_cache = {"token": None, "expiry": 0}


def is_in_singapore(lat: float, lon: float) -> bool:
    return SG_LAT_MIN <= lat <= SG_LAT_MAX and SG_LON_MIN <= lon <= SG_LON_MAX


def _get_token() -> str | None:
    """Returns a cached OneMap token, logging in again only once it's
    within an hour of expiry. Returns None (never raises) if OneMap
    credentials aren't configured or the login call fails, so callers
    can fall back to OpenStreetMap instead of erroring out.
    """

    if not ONEMAP_EMAIL or not ONEMAP_PASSWORD:
        logger.warning("OneMap login skipped: ONEMAP_EMAIL/ONEMAP_PASSWORD not set.")
        return None

    if _token_cache["token"] and time.time() < _token_cache["expiry"] - 3600:
        return _token_cache["token"]

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.post(
                ONEMAP_LOGIN_URL,
                json={"email": ONEMAP_EMAIL, "password": ONEMAP_PASSWORD},
            )
            response.raise_for_status()
            payload = response.json()

        token = payload.get("access_token")
        expiry = payload.get("expiry_timestamp")
        if not token:
            # A 200 with no access_token means OneMap accepted the request
            # but rejected the credentials (e.g. wrong password, or the
            # account was never activated/has expired) — this is the most
            # likely reason every check-in has been falling back to
            # Nominatim. Logging the payload surfaces that instead of
            # silently returning None forever.
            logger.warning(f"OneMap login returned no access_token: {payload}")
            return None

        _token_cache["token"] = token
        # expiry_timestamp from OneMap is a unix timestamp already; fall
        # back to "3 days from now" if it's ever missing/malformed.
        _token_cache["expiry"] = int(expiry) if expiry else time.time() + 3 * 24 * 3600
        return token

    except Exception as e:
        logger.warning(f"OneMap login failed: {e}")
        return None


def reverse_geocode_sg(lat: float, lon: float) -> str | None:
    """Reverse-geocodes a Singapore coordinate via OneMap and returns a
    formatted "Building, Block No, Street, Postal Code" style string,
    or None on any failure (missing credentials, network error, no
    result) — callers should fall back to OpenStreetMap in that case.
    """

    token = _get_token()
    if not token:
        logger.warning(
            "OneMap reverse geocode skipped: no token (missing/invalid "
            "ONEMAP_EMAIL/ONEMAP_PASSWORD, or login is failing — check the "
            "'OneMap login failed' warning above)."
        )
        return None

    try:
        with httpx.Client(timeout=6.0) as client:
            response = client.get(
                ONEMAP_REVGEOCODE_URL,
                params={
                    "location": f"{lat},{lon}",
                    # Was 40 — too tight. OneMap's building match only fires
                    # when a mapped building centroid falls within this
                    # radius, and real GPS fixes (especially indoors / near
                    # tall industrial blocks, which cause Wi-Fi/GPS
                    # multipath) are routinely 50-150m off. That silently
                    # produced zero GeocodeInfo results for check-ins that
                    # were, in reality, right at the building — which is
                    # what sent every one of them to the Nominatim fallback
                    # below instead. 150m is still well under OneMap's 500m
                    # cap and comfortably covers realistic GPS drift.
                    "buffer": 150,
                    "addressType": "All",
                    "otherFeatures": "N",
                },
                headers={"Authorization": token},
            )
            response.raise_for_status()
            payload = response.json()

        results = payload.get("GeocodeInfo") or []
        if not results:
            # Previously swallowed silently, so there was no way to tell
            # "no building within buffer" apart from "token/endpoint
            # broken" apart from "OneMap returned an error body with a 200
            # status" (OneMap does this for some invalid-token cases). Log
            # the raw payload so whichever it is shows up in the server
            # logs instead of just quietly falling back every time.
            logger.warning(
                f"OneMap reverse geocode returned no results for "
                f"({lat}, {lon}); raw response: {payload}"
            )
            return None

        info = results[0]
        building = (info.get("BUILDINGNAME") or "").strip()
        block = (info.get("BLOCK") or "").strip()
        road = (info.get("ROAD") or "").strip()
        postal = (info.get("POSTALCODE") or "").strip()

        # Drop OneMap's placeholder "NIL" values and blanks.
        def clean(v):
            return v if v and v.upper() != "NIL" else None

        building, block, road, postal = (
            clean(building),
            clean(block),
            clean(road),
            clean(postal),
        )

        street_line = " ".join(p for p in [block, road] if p) or None
        parts = [building, street_line, "Singapore", postal]
        parts = [p for p in parts if p]

        return ", ".join(parts) if parts else None

    except Exception as e:
        logger.warning(f"OneMap reverse geocode failed: {e}")
        return None
