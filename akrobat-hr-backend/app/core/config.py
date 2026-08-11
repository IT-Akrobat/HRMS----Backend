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

# ---------------------------------------------------------------------
# Documents module — file storage (see app/documents/services.py)
# ---------------------------------------------------------------------
# Supabase Storage bucket that self-service document uploads (the "+" on
# My Profile > Documents Summary) are written to. Create this bucket in
# the Supabase dashboard (Storage) as PRIVATE — documents are treated as
# confidential (see sql/006_document_permissions_seed.sql) and must only
# ever be served back out through the authenticated
# GET /documents/{id}/file and GET /documents/download-all endpoints,
# never a public bucket URL. Read with os.getenv (not get_env()) so a
# missing var doesn't block the whole app from starting — only the
# Documents upload/download endpoints would fail until it's set.
SUPABASE_DOCUMENTS_BUCKET = os.getenv("SUPABASE_DOCUMENTS_BUCKET", "employee-documents")

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


# ---------------------------------------------------------------------
# Web Push (see app/core/push.py, app/push_subscriptions)
# ---------------------------------------------------------------------
# Optional and read with os.getenv (not get_env()) -- same
# degrade-gracefully pattern as SMTP/Pexels/OneMap above. Generate a
# pair once with:
#   python -m scripts.generate_vapid_keys
# and set them as env vars. If unset, push sends are skipped (logged,
# not raised) and every other notification path keeps working exactly
# as before.
def _normalize_vapid_private_key(raw: str | None) -> str | None:
    """
    Host env-var UIs (Render included) are inconsistent about how a
    multi-line PEM block survives copy/paste -- literal backslash-n
    sequences instead of real newlines, a stray wrapping quote, or
    leading/trailing whitespace all produce the same cryptography
    error at push-send time ("ASN.1 parsing error: invalid length")
    with no indication of which of those it actually was. Normalize
    all three here instead of debugging it via production logs.
    """
    if not raw:
        return raw
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    return raw.replace("\\n", "\n")


VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = _normalize_vapid_private_key(os.getenv("VAPID_PRIVATE_KEY"))
# Web Push requires a contact per RFC 8292 so push services can reach
# you about a misbehaving sender -- any mailto: works.
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@akrobat.com")
