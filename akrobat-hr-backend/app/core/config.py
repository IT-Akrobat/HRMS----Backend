import os

from dotenv import load_dotenv

load_dotenv()


def get_env(key: str, default: str | None = None):
    value = os.getenv(key, default)

    if value is None:
        raise ValueError(f"Missing environment variable: {key}")

    return value


SUPABASE_URL = get_env("SUPABASE_URL")

SUPABASE_ANON_KEY = get_env("SUPABASE_ANON_KEY")

SUPABASE_SERVICE_ROLE_KEY = get_env("SUPABASE_SERVICE_ROLE_KEY")

SUPABASE_JWT_SECRET = get_env("SUPABASE_JWT_SECRET")

APP_NAME = os.getenv("APP_NAME", "Akrobat HRMS")

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Comma-separated list of allowed CORS origins, e.g.
# "https://app.example.com,https://admin.example.com". Falls back to the
# local Vite dev server so `npm run dev` keeps working without any env setup.
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

# ---------------------------------------------------------------------
# Quote of the Day (see app/dashboard/services.get_quote_of_day)
# ---------------------------------------------------------------------
# Both optional and intentionally read with os.getenv (not get_env()):
# get_env() raises and kills app startup if the var is missing, but this
# feature is designed to degrade gracefully (curated fallback content)
# rather than take the whole API down when a key isn't configured yet.

# Public, keyless random-quote API. Swap via env if it ever goes down.
QUOTE_API_URL = os.getenv("QUOTE_API_URL", "https://zenquotes.io/api/random")

# ---------------------------------------------------------------------
# SMTP (see app/core/email.py, used by app/notifications "Email
# notifications" preference)
# ---------------------------------------------------------------------
# Entirely optional -- same degrade-gracefully pattern as QUOTE_API_URL.
# If SMTP_HOST isn't set, email.send_email() just logs and no-ops instead
# of raising, so a notification insert never fails because email wasn't
# configured yet.

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

# Pexels image search (https://www.pexels.com/api/) — free API key.
# Background images fall back to a curated static list when unset.
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PEXELS_SEARCH_QUERY = os.getenv(
    "PEXELS_SEARCH_QUERY", "workplace safety construction teamwork"
)

# ---------------------------------------------------------------------
# OneMap Singapore (see app/locations/onemap_service.py)
# ---------------------------------------------------------------------
# Free account at https://www.onemap.gov.sg/apidocs/register. Optional
# and read with os.getenv (not get_env()) — same degrade-gracefully
# pattern as Pexels above: if unset, reverse-geocode requests for
# Singapore coordinates just fall back to OpenStreetMap on the
# frontend instead of the app failing to start.
ONEMAP_EMAIL = os.getenv("ONEMAP_EMAIL")
ONEMAP_PASSWORD = os.getenv("ONEMAP_PASSWORD")
